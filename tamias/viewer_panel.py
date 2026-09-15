# ============================================================
# 栗栗（Tamias）— 专业模式右侧「查看器面板」
# ============================================================
# 把专业模式右侧原来那条 240px 的项目面板，改造成「可拖拽调宽」的
# 查看器：顶部常驻干活引擎状态条，下面用标签页切「文件树 / 日志 / 文档」
# （借鉴 VS Code 底部 Panel 的 view tab：点标题切换、切换只 show/hide 状态保留）。
#
# 分三个子页：
#   - FileTreePage：完整文件树浏览（QTreeView + QFileSystemModel），
#     点文件在下方预览内容（过滤 .git/.tamias/node_modules 等噪音目录）。
#   - LogPage：看运行/门禁/崩溃日志，2s 轮询 + 自动滚底 + 用户名脱敏。
#   - DocPage：看使用说明（QTextBrowser.setMarkdown 渲染）。协议/隐私在首次引导已展示，这里不放。
#
# 主题：不带统一色板（见 theme.py 注释），这里自带深色/暖棕双调色板，
# 由 apply_theme(dark) 一次刷新状态条 + 标签页 + 三个子页。
# ============================================================

import os
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, Signal, QDir, QSortFilterProxyModel, QUrl,
)
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTreeView, QFileSystemModel, QTextEdit, QTextBrowser,
    QComboBox, QSplitter, QStackedWidget, QPlainTextEdit, QScrollArea,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
)

from tamias.i18n import tr
from tamias.fonts import mono_font, ui_font
from tamias import app_log
from tamias import memory_store
from tamias.usage_viewer import USAGE_DIR, USAGE_FILES
from tamias.ui_icons import icon, strip_leading_emoji
from tamias.theme import WARM, DARK


# 文件树里要藏起来的噪音目录（普通用户不需要看到，也不该误点进去）
_NOISE_DIRS = {
    ".git", ".tamias", ".idea", ".vscode", ".venv", "venv",
    "node_modules", "__pycache__", "dist", "build",
}

# 文件预览的体积上限（字节）：超过就不读、只提示，避免点到大文件卡 UI
_PREVIEW_MAX_BYTES = 1_000_000

# 日志每页最多显示的末尾行数（tail，避免日志太长撑爆界面）
_LOG_TAIL_LINES = 200


# ============================================================
# 文件树过滤代理：只藏噪音目录，其余全部放行
# ============================================================
class _NoiseFilterProxy(QSortFilterProxyModel):
    """把 QFileSystemModel 里的噪音目录（.git/node_modules 等）从树上藏掉。"""

    def filterAcceptsRow(self, row, parent):
        src = self.sourceModel()
        index = src.index(row, 0, parent)
        if index.isValid() and src.fileName(index) in _NOISE_DIRS:
            return False
        return True


# ============================================================
# 子页一：文件树 + 多格式预览
# ============================================================
def _extract_docx_text(path: str) -> str:
    """从 .docx 提取正文纯文本（docx 是 zip，正文在 word/document.xml，零依赖）。
    按段落拆行，标题/表格里的文字也一并平铺，够预览用。"""
    import zipfile
    from xml.etree import ElementTree
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return ""
    lines = []
    for p in root.iter(W + "p"):
        line = "".join(t.text or "" for t in p.iter(W + "t"))
        lines.append(line)
    return "\n".join(lines)


class FileTreePage(QWidget):
    """文件树 + 预览页：点文件按类型预览——代码/文本（等宽）、Markdown、
    Word(.docx 提取文本)、HTML 网页（QWebEngine 渲染）、图片；其余只提示。"""

    # 文本/代码扩展名（等宽只读预览）
    _TEXT_EXTS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".scss", ".json", ".yaml",
        ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".log", ".txt", ".text",
        ".sh", ".bat", ".ps1", ".c", ".cpp", ".h", ".hpp", ".java", ".go", ".rs",
        ".rb", ".php", ".sql", ".xml", ".csv", ".vue", ".svelte", ".gitignore",
    }
    _MD_EXTS = {".md", ".markdown"}
    _HTML_EXTS = {".html", ".htm"}
    _DOCX_EXTS = {".docx"}
    _IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico"}

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._dark = False
        self._web_view = None  # HTML 预览懒创建（QWebEngine 重，用到才起，省内存）
        # 可编辑文本预览的状态：当前文件路径 / 是否有未保存改动 / 是否正在载入
        self._current_editable = None
        self._dirty = False
        self._loading = False

        split = QSplitter(Qt.Orientation.Horizontal, self)

        # —— 文件树（贴窗口最右）——
        self._model = QFileSystemModel()
        self._model.setFilter(
            QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs | QDir.Filter.Files
        )
        self._proxy = _NoiseFilterProxy()
        self._proxy.setSourceModel(self._model)

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setHeaderHidden(True)  # 只留文件名，不要 Size/Type/Date 表头
        for col in (1, 2, 3):
            self._tree.hideColumn(col)
        self._tree.clicked.connect(self._on_clicked)

        # —— 预览器（QStackedWidget 按文件类型切 view，放树左边）——
        self._stack = QStackedWidget()

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.textChanged.connect(self._on_text_changed)

        self._md_view = QTextBrowser()
        self._md_view.setOpenExternalLinks(True)

        self._img_view = QLabel()
        self._img_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_scroll = QScrollArea()
        self._img_scroll.setWidgetResizable(True)
        self._img_scroll.setWidget(self._img_view)

        self._empty_view = QLabel()
        self._empty_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_view.setWordWrap(True)

        # index：0 空/提示  1 文本/代码/Word  2 Markdown  3 图片  （4 HTML 懒创建）
        self._stack.addWidget(self._empty_view)
        self._stack.addWidget(self._text_view)
        self._stack.addWidget(self._md_view)
        self._stack.addWidget(self._img_scroll)

        split.addWidget(self._stack)   # 预览在左
        split.addWidget(self._tree)    # 文件树贴最右
        split.setStretchFactor(0, 3)   # 预览区占大头
        split.setStretchFactor(1, 2)   # 树窄一点
        # 初始尺寸：预览宽、树窄（否则 QTreeView sizeHint 宽，把预览区压扁）
        split.setSizes([320, 220])

        # 顶部工具条：当前文件名 + 保存按钮（只对可编辑文本文件亮起）
        bar = QHBoxLayout()
        self._file_label = QLabel("")
        self._file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._save_btn = QPushButton(tr("保存"))
        self._save_btn.setEnabled(False)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._save_current)
        bar.addWidget(self._file_label, stretch=1)
        bar.addWidget(self._save_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addLayout(bar)
        lay.addWidget(split, stretch=1)

        # 初始根目录
        self.set_root(self._resolve_work_dir())
        # 初始空状态
        self._show_empty(tr("点左边的文件预览内容\n代码 / Word / 网页 / 图片都能看"))

    def _resolve_work_dir(self) -> str:
        # 文件树默认浏览「项目根目录」（代码/文档/网页都在这里），
        # 让用户一打开专业模式就有文件可点、能立刻试预览；
        # 用户「打开文件夹」选中干活目录后，再经 set_work_dir 切过去。
        return str(Path(__file__).resolve().parent.parent)

    def set_root(self, path: str):
        """把文件树根指到工作目录，并展开根一级。"""
        if not path:
            return
        p = str(path)
        self._model.setRootPath(p)
        root_index = self._proxy.mapFromSource(self._model.index(p))
        self._tree.setRootIndex(root_index)
        self._tree.expand(root_index)

    def _on_clicked(self, proxy_index):
        """点树：文件→预览，目录→单击展开/收起。"""
        src = self._proxy.mapToSource(proxy_index)
        fp = self._model.filePath(src)
        if not os.path.isfile(fp):
            # 点的是目录：单击展开/收起。QTreeView 默认单击目录只选中不展开，
            # 用户点文件夹「没反应」会以为坏了，这里对齐 Windows 文件管理器：单击展开。
            if self._tree.isExpanded(proxy_index):
                self._tree.collapse(proxy_index)
            else:
                self._tree.expand(proxy_index)
            return
        self._preview_file(fp)

    def _preview_file(self, fp: str):
        """按扩展名分派预览器：图片 / HTML / Word / Markdown / 文本。"""
        path = Path(fp)
        ext = path.suffix.lower()

        # 工具条统一先显示当前文件路径（不管下面能不能编辑）
        self._file_label.setText(fp)
        self._file_label.setToolTip(fp)

        # 二进制/超大先挡掉（图片不设 1MB 上限，单独走图片分支）
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size > _PREVIEW_MAX_BYTES and ext not in self._IMG_EXTS:
            self._clear_editable()
            self._show_empty(tr("文件太大（>1MB），不预览"))
            return

        if ext in self._IMG_EXTS:
            self._clear_editable()
            self._show_image(path)
            return
        if ext in self._HTML_EXTS:
            self._clear_editable()
            self._show_html(path)
            return
        if ext in self._DOCX_EXTS:
            self._clear_editable()
            self._show_docx(path)
            return

        # 其余按文本读（先探测二进制）
        try:
            with open(fp, "rb") as f:
                head = f.read(512)
        except OSError:
            self._clear_editable()
            self._show_empty(tr("文件读取失败：{}", fp))
            return
        if b"\x00" in head:
            self._clear_editable()
            self._show_empty(tr("二进制文件，不预览"))
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._clear_editable()
            self._show_empty(tr("文件读取失败：{}", fp))
            return
        if ext in self._MD_EXTS:
            # Markdown 用渲染视图（只读）；要改 .md 目前先按只读预览处理
            self._clear_editable()
            self._md_view.setMarkdown(text)
            self._stack.setCurrentWidget(self._md_view)
        else:
            # 纯文本/代码文件：装进可编辑预览，允许改 + 保存
            self._show_text_editable(fp, text)

    def _show_text_editable(self, fp: str, text: str):
        """把纯文本/代码文件装入可编辑预览：允许修改，保存按钮随改动点亮。"""
        self._current_editable = fp
        self._text_view.setReadOnly(False)
        self._loading = True
        self._text_view.setPlainText(text)
        self._loading = False
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._stack.setCurrentWidget(self._text_view)

    def _clear_editable(self):
        """切到非文本预览（图片/HTML/Word/Markdown/空态）时，撤销可编辑态。"""
        self._current_editable = None
        self._text_view.setReadOnly(True)
        self._dirty = False
        self._save_btn.setEnabled(False)

    def _on_text_changed(self):
        """文本被用户改动 → 置脏、点亮保存。载入文件时的 programmatic 改动被 _loading 抑制。"""
        if self._loading:
            return
        if self._current_editable:
            self._dirty = True
            self._save_btn.setEnabled(True)

    def _save_current(self):
        """把当前编辑的文本写回磁盘（覆盖原文件，UTF-8）。"""
        fp = self._current_editable
        if not fp:
            return
        try:
            Path(fp).write_text(self._text_view.toPlainText(), encoding="utf-8")
        except OSError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("栗栗"), tr("保存失败：{}\n{}", fp, e))
            return
        self._dirty = False
        self._save_btn.setEnabled(False)

    def _show_empty(self, msg: str):
        self._empty_view.setText(msg)
        self._stack.setCurrentWidget(self._empty_view)

    def _show_docx(self, path: Path):
        text = _extract_docx_text(str(path))
        if not text.strip():
            self._show_empty(tr("Word 文档读取失败（可能不是有效 .docx）：{}", str(path)))
            return
        self._text_view.setPlainText(text)
        self._stack.setCurrentWidget(self._text_view)

    def _show_html(self, path: Path):
        """HTML 用 QWebEngineView 渲染成网页（与 Live2D 同一个 WebEngine 库，不新增依赖）。
        view 懒创建，第一次点 html 才起渲染进程。"""
        if self._web_view is None:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEngineSettings
            self._web_view = QWebEngineView()
            settings = self._web_view.page().settings()
            # 允许 file:// 页面读同目录相对资源（css/js/图片），否则本地网页渲染不全
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            self._stack.addWidget(self._web_view)  # index 4
        self._web_view.load(QUrl.fromLocalFile(str(path)))
        self._stack.setCurrentWidget(self._web_view)

    def _show_image(self, path: Path):
        pm = QPixmap(str(path))
        if pm.isNull():
            self._show_empty(tr("图片读取失败：{}", str(path)))
            return
        # 缩放到预览区宽度（KeepAspectRatio），避免超大图撑爆界面
        target_w = max(1, self._img_scroll.viewport().width() - 8)
        self._img_view.setPixmap(
            pm.scaledToWidth(target_w, Qt.TransformationMode.SmoothTransformation))
        self._stack.setCurrentWidget(self._img_scroll)

    def apply_theme(self, dark: bool):
        self._dark = dark
        c = DARK if dark else WARM
        if dark:
            tree_bg, tree_fg, tree_sel = c["bg"], c["text"], c["divider"]
            txt_bg, txt_fg, txt_bd = c["bg"], c["text"], c["divider"]
            empty_fg = c["muted"]
            label_fg = c["muted"]
            btn_qss = (f"QPushButton{{background:{c['card']};color:{c['muted']};border:1px solid {c['border']};"
                       "border-radius:3px;padding:3px 10px;}"
                       f"QPushButton:hover{{background:{c['hover_bg']};color:{c['success']};}}"
                       f"QPushButton:disabled{{background:{c['card']};color:#555;border:1px solid {c['divider']};}}")
        else:
            tree_bg, tree_fg, tree_sel = c["card"], c["text"], c["card_soft"]
            txt_bg, txt_fg, txt_bd = c["white"], c["text"], c["divider"]
            empty_fg = c["title"]
            label_fg = c["title"]
            btn_qss = (f"QPushButton{{background:{c['card']};color:{c['title']};border:1px solid {c['border']};"
                       "border-radius:3px;padding:3px 10px;}"
                       f"QPushButton:hover{{background:{c['bg']};color:{c['primary']};}}"
                       f"QPushButton:disabled{{background:#F7F2EA;color:#C4B4A6;border:1px solid {c['divider']};}}")
        self._tree.setStyleSheet(
            f"QTreeView {{ background:{tree_bg}; color:{tree_fg}; border:none; }}"
            f"QTreeView::item:selected {{ background:{tree_sel}; color:{tree_fg}; }}"
        )
        self._text_view.setStyleSheet(
            f"QPlainTextEdit {{ background:{txt_bg}; color:{txt_fg}; border:1px solid {txt_bd}; }}"
        )
        self._text_view.setFont(mono_font(9))
        self._md_view.setStyleSheet(
            f"QTextBrowser {{ background:{txt_bg}; color:{txt_fg}; border:1px solid {txt_bd}; }}"
        )
        self._empty_view.setStyleSheet(f"color:{empty_fg};")
        self._img_scroll.setStyleSheet(
            f"QScrollArea {{ background:{txt_bg}; border:1px solid {txt_bd}; }}"
        )
        self._file_label.setStyleSheet(f"color:{label_fg};")
        self._save_btn.setStyleSheet(btn_qss)


# ============================================================
# 子页一·五：对话列表（像文件树一样点对话切换）
# ============================================================
class ConvPage(QWidget):
    """对话列表页：像文件树一样列「当前项目」的对话，点一条切换。
    每个对话节点显示标题（主）+ 原始 json 文件名（辅、灰字），根节点是当前项目名。
    数据由 ChatDialog 通过 set_conversations 推入（纯视图，不碰 store）。"""

    conversation_selected = Signal(str)  # 点了某条对话 → 携带 conv_id，交给 ChatDialog._load_conversation

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._dim = "#888888"  # 文件名灰字颜色（随主题更新）

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)  # 只留节点文字，不要表头（像文件树）
        self._tree.setColumnCount(2)
        self._tree.setColumnWidth(0, 180)   # 标题列（主）
        self._tree.header().setStretchLastSection(True)  # 文件名列（辅、灰字）拉伸填满，截断 + tooltip 看全
        self._tree.itemClicked.connect(self._on_item_clicked)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addWidget(self._tree)

    def set_conversations(self, convs, current_id: str = "", project_name: str = ""):
        """把「当前项目」的对话列表刷进树。convs 是 Conversation 列表（已按 updated_at 倒序）。
        current_id 高亮为当前对话；project_name 作为根节点显示名。"""
        self._tree.clear()
        root = QTreeWidgetItem([project_name or tr("对话"), ""])
        root.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 根节点只当分组，不可选/不可点
        f = root.font(0)
        f.setBold(True)
        root.setFont(0, f)
        self._tree.addTopLevelItem(root)
        for c in convs:
            fname = f"{c.id}.json"
            item = QTreeWidgetItem([c.title or tr("无标题"), fname])
            item.setData(0, Qt.ItemDataRole.UserRole, c.id)
            item.setForeground(1, QColor(self._dim))  # 文件名灰字（辅）
            item.setToolTip(1, fname)                 # 截断时悬停看完整文件名
            if c.id == current_id:
                cf = item.font(0)
                cf.setBold(True)
                item.setFont(0, cf)                   # 当前对话加粗
            root.addChild(item)
        self._tree.expandAll()

    def _on_item_clicked(self, item, column):
        """点叶子（对话）→ 发切换信号；点根节点（无 conv_id）→ 忽略。"""
        conv_id = item.data(0, Qt.ItemDataRole.UserRole)
        if conv_id:
            self.conversation_selected.emit(conv_id)

    def apply_theme(self, dark: bool):
        self._dark = dark
        c = DARK if dark else WARM
        if dark:
            tree_bg, tree_fg, tree_sel = c["bg"], c["text"], c["divider"]
            self._dim = c["muted"]
        else:
            tree_bg, tree_fg, tree_sel = c["card"], c["text"], c["card_soft"]
            self._dim = c["title"]
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background:{tree_bg}; color:{tree_fg}; border:none; }}"
            f"QTreeWidget::item:selected {{ background:{tree_sel}; color:{tree_fg}; }}"
        )


# ============================================================
# 子页二：日志
# ============================================================
class LogPage(QWidget):
    """看日志：下拉选 run.log/gate.log/crash.log，2s 轮询 + 自动滚底 + 脱敏。"""

    # 显示名（中文原文 = i18n key）→ 日志文件名。不含 chat.log（对话隐私，见 app_log）。
    _LOG_FILES = [
        ("运行日志", "run.log"),
        ("门禁日志", "gate.log"),
        ("崩溃日志", "crash.log"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._names = [name for name, _ in self._LOG_FILES]

        self._combo = QComboBox()
        for name in self._names:
            self._combo.addItem(tr(name))
        self._combo.currentIndexChanged.connect(self._reload)

        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setFont(mono_font(9))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addWidget(self._combo)
        lay.addWidget(self._view, stretch=1)

        # 2s 轮询刷新（项目无 QFileSystemWatcher，轮询最简单稳）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)
        self._reload()

    def _current_path(self) -> Path:
        return app_log.get_logs_dir() / self._LOG_FILES[self._combo.currentIndex()][1]

    def _read_tail(self) -> str:
        path = self._current_path()
        if not path.exists():
            return tr("（暂无日志）")
        try:
            data = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return tr("日志读取失败")
        lines = data.splitlines()
        return "\n".join(lines[-_LOG_TAIL_LINES:])

    def _refresh(self):
        """轮询刷新：之前挂在底部就自动滚到底（smart scroll），往上翻过就暂停。"""
        sb = self._view.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20
        self._view.setPlainText(app_log.mask_path(self._read_tail()))
        if at_bottom:
            sb.setValue(sb.maximum())

    def _reload(self):
        """切日志文件 → 全量重读并滚到底。"""
        self._refresh()
        self._view.verticalScrollBar().setValue(
            self._view.verticalScrollBar().maximum()
        )

    def apply_theme(self, dark: bool):
        self._dark = dark
        c = DARK if dark else WARM
        if dark:
            combo_qss = (f"QComboBox{{background:{c['card']};color:{c['text']};border:1px solid {c['border']};}}"
                         f"QComboBox QAbstractItemView{{background:{c['card']};color:{c['text']};"
                         f"selection-background-color:{c['divider']};}}")
            view_bg, view_fg, view_bd = c["bg"], c["text"], c["divider"]
        else:
            combo_qss = (f"QComboBox{{background:{c['card']};color:{c['text']};border:1px solid {c['border']};}}"
                         f"QComboBox QAbstractItemView{{background:{c['card']};color:{c['text']};"
                         f"selection-background-color:{c['card_soft']};}}")
            view_bg, view_fg, view_bd = c["white"], c["text"], c["divider"]
        self._combo.setStyleSheet(combo_qss)
        self._view.setStyleSheet(
            f"QTextEdit {{ background:{view_bg}; color:{view_fg}; border:1px solid {view_bd}; }}"
        )


# ============================================================
# 子页三：文档
# ============================================================
class DocPage(QWidget):
    """直接看「使用说明」（= 栗栗能干什么），QTextBrowser.setMarkdown 渲染 Markdown。
    协议/隐私政策在首次引导（同意《用户协议》+《隐私政策》弹窗）已展示过，这里不重复放，
    避免文档页堆满没人看的静态页。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addWidget(self._browser, stretch=1)
        self._load()

    def _load(self):
        path = USAGE_DIR / USAGE_FILES["使用说明"]
        if path.exists():
            try:
                md = path.read_text(encoding="utf-8")
            except OSError:
                md = tr("文档读取失败：{}", str(path))
        else:
            md = tr("文档缺失：{}", str(path))
        self._browser.setMarkdown(md)

    def apply_theme(self, dark: bool):
        self._dark = dark
        c = DARK if dark else WARM
        if dark:
            br_bg, br_fg, br_bd = c["bg"], c["text"], c["divider"]
        else:
            br_bg, br_fg, br_bd = c["white"], c["text"], c["border"]
        self._browser.setStyleSheet(
            f"QTextBrowser {{ background:{br_bg}; color:{br_fg}; border:1px solid {br_bd}; }}"
        )


# ============================================================
# 子页四：记忆（长期记忆的「看到 / 修改 / 删除」入口）
# ============================================================
class MemoryPage(QWidget):
    """记忆管理页：列出栗栗记住的所有记忆（每条 = 一个 SKILL.md，见 memory_store）。
    点选查看正文，可编辑保存、删除。记忆本体由 dsh 的 skill 系统自动发现，
    本页只是「用户可见 / 可改 / 可删」的界面入口（对应 Claude Code 的 memory 文件）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._memories = []          # [(slug, desc, type, path)]
        self._current_slug = None
        self._current_desc = ""
        self._current_type = memory_store.TYPE_PROJECT

        split = QSplitter(Qt.Orientation.Horizontal, self)

        # —— 左：记忆清单（显示描述，描述空则用 slug 兜底）——
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        split.addWidget(self._list)

        # —— 右：正文编辑 + 保存/删除/刷新 ——
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(4)

        self._view = QPlainTextEdit()
        self._view.setPlaceholderText(tr("还没有记忆。对栗栗说「记住 XXX」，就能存一条。"))
        rlay.addWidget(self._view, stretch=1)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        self._new_btn = QPushButton(tr("新建"))
        self._save_btn = QPushButton(tr("保存"))
        self._delete_btn = QPushButton(tr("删除"))
        self._refresh_btn = QPushButton(tr("刷新"))
        self._new_btn.clicked.connect(self._on_new)
        self._save_btn.clicked.connect(self._on_save)
        self._delete_btn.clicked.connect(self._on_delete)
        self._refresh_btn.clicked.connect(self._reload)
        btns.addWidget(self._new_btn)
        btns.addWidget(self._save_btn)
        btns.addWidget(self._delete_btn)
        btns.addStretch()
        btns.addWidget(self._refresh_btn)
        rlay.addLayout(btns)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([220, 360])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(split)

        self._reload()

    # ---------- 数据 ----------

    def _reload(self):
        """重读记忆目录，刷新清单（记忆清空则回到空态）。"""
        self._memories = memory_store.list_memories()
        self._list.blockSignals(True)
        self._list.clear()
        for slug, desc, mtype, _path in self._memories:
            it = QListWidgetItem(desc or slug)
            it.setData(Qt.ItemDataRole.UserRole, slug)
            it.setToolTip(tr("类型：{}", mtype))
            self._list.addItem(it)
        self._list.blockSignals(False)
        self._current_slug = None
        self._view.clear()
        if self._memories:
            self._list.setCurrentRow(0)

    def _select_slug(self, slug: str):
        """按 slug 重新选中清单里的某一项（保存后拉回原选中，不跳回第 0 条）。"""
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == slug:
                self._list.setCurrentRow(i)
                return

    # ---------- 交互 ----------

    def _on_select(self, current, previous):
        """点选某条记忆 → 正文读进编辑区，并记住它的 slug/描述/类型（保存时原样写回）。"""
        if current is None:
            return
        slug = current.data(Qt.ItemDataRole.UserRole)
        for s, desc, mtype, _path in self._memories:
            if s == slug:
                self._current_slug = slug
                self._current_desc = desc
                self._current_type = mtype
                self._view.setPlainText(memory_store.read_memory(slug))
                break

    def _on_save(self):
        """把编辑区正文写回当前记忆（保留原 slug/描述/类型）。"""
        if not self._current_slug:
            return
        memory_store.write_memory_at(
            self._current_slug, self._view.toPlainText(),
            self._current_desc, self._current_type,
        )
        self._reload()
        self._select_slug(self._current_slug)

    def _on_delete(self):
        """删掉当前选中的记忆。"""
        if not self._current_slug:
            return
        memory_store.delete_memory(self._current_slug)
        self._reload()

    def _on_new(self):
        """新建一条记忆：弹小框输一句话 → 存成 user 类型（对齐聊天「记住」命令）。
        写完后选中新记忆，主人可在右侧正文区继续编辑补 Why/How。"""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, tr("新建记忆"), tr("这条记忆记什么？（一句话）"))
        text = (text or "").strip()
        if not ok or not text:
            return
        # 用输入的一句话做正文和描述，类型 user（跟「记住」命令一致，聊天会注入）
        path = memory_store.write_memory(
            text, text,
            description=text[:20].replace("\n", " "),
            mem_type=memory_store.TYPE_USER,
        )
        self._reload()
        self._select_slug(path.parent.name)
        self._view.setFocus()

    # ---------- 主题 ----------

    def apply_theme(self, dark: bool):
        self._dark = dark
        c = DARK if dark else WARM
        if dark:
            list_qss = (f"QListWidget{{background:{c['bg']};color:{c['text']};border:1px solid {c['divider']};}}"
                        f"QListWidget::item:selected{{background:{c['divider']};color:{c['text']};}}")
            view_qss = f"QPlainTextEdit{{background:{c['bg']};color:{c['text']};border:1px solid {c['divider']};}}"
            btn_qss = (f"QPushButton{{background:{c['card']};color:{c['muted']};border:1px solid {c['border']};"
                       "border-radius:3px;padding:3px 10px;}"
                       f"QPushButton:hover{{background:{c['hover_bg']};color:{c['success']};}}")
        else:
            list_qss = (f"QListWidget{{background:{c['white']};color:{c['text']};border:1px solid {c['divider']};}}"
                        f"QListWidget::item:selected{{background:{c['card_soft']};color:{c['text']};}}")
            view_qss = f"QPlainTextEdit{{background:{c['white']};color:{c['text']};border:1px solid {c['divider']};}}"
            btn_qss = (f"QPushButton{{background:{c['card']};color:{c['title']};border:1px solid {c['border']};"
                       "border-radius:3px;padding:3px 10px;}"
                       f"QPushButton:hover{{background:{c['bg']};color:{c['primary']};}}")
        self._list.setStyleSheet(list_qss)
        self._view.setStyleSheet(view_qss)
        self._view.setFont(mono_font(9))
        for b in (self._new_btn, self._save_btn, self._delete_btn, self._refresh_btn):
            b.setStyleSheet(btn_qss)


# ============================================================
# 主面板：状态条 + 四个标签页
# ============================================================
class ViewerPanel(QWidget):
    """专业模式右侧查看器面板。顶部常驻引擎状态条，下面 QTabWidget 切三页。"""

    rollback_requested = Signal()          # 点「↩ 回滚」→ 交给 ChatDialog._open_rollback
    conversation_selected = Signal(str)    # 点「对话」标签页某条 → ChatDialog._load_conversation
    _engine_refreshed = Signal(bool)       # 手动刷新 dsh 完成（后台线程 → 主线程）
    _balance_fetched = Signal(str)         # 余额拉取完成（后台线程 → 主线程刷新显示）

    def __init__(self, settings, refresh_dsh=None, dsh_status=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._refresh_dsh = refresh_dsh  # 手动刷新 dsh 回调（后台线程跑，返回 bool）
        self._dsh_status = dsh_status    # 查询 dsh 连接状态回调（'ok'/'down'）
        self._dark = False

        self._build_ui()
        self._engine_refreshed.connect(self._on_engine_refreshed)
        self._balance_fetched.connect(self._on_balance_fetched)
        # 首次打开刷一次引擎状态灯（探测是本地 HTTP，很快；singleShot 不阻塞构造）
        QTimer.singleShot(0, self.refresh_engine_status)
        # 首次打开拉一次余额（网络请求，后台线程跑，不阻塞构造）
        QTimer.singleShot(0, self.refresh_balance)

    # ---------- 界面搭建 ----------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # —— 引擎状态条（常驻，不管切哪个 tab 都可见）——
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(6)

        self._engine_dot = QLabel("●")
        self._engine_dot.setFont(ui_font(11))
        self._engine_status_lb = QLabel(tr("引擎连接中…"))
        self._engine_status_lb.setFont(mono_font(9))
        self._refresh_engine_btn = QPushButton(tr("刷新"))
        self._refresh_engine_btn.setFont(mono_font(9))
        self._refresh_engine_btn.clicked.connect(self._on_refresh_engine)

        self._work_dir_lb = QLabel("")
        self._work_dir_lb.setFont(mono_font(8))

        # 余额显示：点击即可重新拉取 DeepSeek 余额（后台线程，不卡 UI）
        self._balance_btn = QPushButton(tr("余额 —"))
        self._balance_btn.setFont(mono_font(8))
        self._balance_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._balance_btn.setToolTip(tr("DeepSeek 账户余额，点击刷新"))
        self._balance_btn.clicked.connect(self.refresh_balance)

        self._rollback_btn = QPushButton(strip_leading_emoji(tr("↩ 回滚")))
        self._rollback_btn.setFont(mono_font(9))
        self._rollback_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rollback_btn.clicked.connect(self.rollback_requested.emit)

        bar.addWidget(self._engine_dot)
        bar.addWidget(self._engine_status_lb)
        bar.addWidget(self._refresh_engine_btn)
        bar.addStretch()
        bar.addWidget(self._work_dir_lb)
        bar.addWidget(self._balance_btn)
        bar.addWidget(self._rollback_btn)
        outer.addLayout(bar)

        # —— 五个标签页 ——
        self._tabs = QTabWidget()
        self._file_page = FileTreePage(self._settings)
        self._conv_page = ConvPage()
        self._log_page = LogPage()
        self._doc_page = DocPage()
        self._mem_page = MemoryPage()
        self._tabs.addTab(self._file_page, strip_leading_emoji(tr("📁 文件")))
        self._tabs.addTab(self._conv_page, strip_leading_emoji(tr("💬 对话")))
        self._tabs.addTab(self._log_page, strip_leading_emoji(tr("📄 日志")))
        self._tabs.addTab(self._doc_page, strip_leading_emoji(tr("📜 文档")))
        self._tabs.addTab(self._mem_page, strip_leading_emoji(tr("🧠 记忆")))
        outer.addWidget(self._tabs, stretch=1)
        # 对话页点击 → 转发给上层（ChatDialog 里 connect 到 _load_conversation）
        self._conv_page.conversation_selected.connect(self.conversation_selected.emit)

        # 初始工作目录
        self.set_work_dir("")
        self._apply_icons()

    # ---------- 引擎状态（从 ChatDialog 迁来）----------

    def _on_refresh_engine(self):
        """点「刷新」：后台线程重建 dsh 链路，避免慢启动（最多 60s）卡 UI。"""
        if self._refresh_dsh is None:
            self._set_engine_status("down")
            return
        self._refresh_engine_btn.setEnabled(False)
        self._set_engine_status("busy")
        import threading
        threading.Thread(target=self._run_engine_refresh, daemon=True).start()

    def _run_engine_refresh(self):
        """后台线程：调刷新回调，结果通过信号送回主线程更新状态灯。"""
        ok = False
        try:
            ok = bool(self._refresh_dsh())
        except Exception:
            ok = False
        self._engine_refreshed.emit(ok)

    def _on_engine_refreshed(self, ok: bool):
        """刷新完成（主线程）：恢复按钮 + 按结果更新状态灯。"""
        self._refresh_engine_btn.setEnabled(True)
        self._set_engine_status("ok" if ok else "down")

    def refresh_engine_status(self):
        """读当前 dsh 连接状态并刷新状态灯（打开面板/切专业模式时调用）。"""
        if self._dsh_status is None:
            self._set_engine_status("down")
            return
        try:
            state = self._dsh_status()
        except Exception:
            state = "down"
        self._set_engine_status(state)

    def _set_engine_status(self, state: str):
        """状态灯配色：ok=绿●已连接 / down=红●未连接 / busy=黄●刷新中…。
        刷新按钮只在「未连接 / 刷新中」可见——已连接就藏起来，从根上杜绝手贱
        连续点刷新（每次刷新都会 cancel 当前任务 + stop 旧网关再冷启动重建，
        已连接时点它纯属破坏性空耗）。代价是「探测说已连接、链路实际半死」这种
        边缘场景没法手动救，但概率低，有断线自愈 + 重启栗栗兜底。"""
        if state == "ok":
            self._engine_dot.setStyleSheet("color:#00AA44;")
            self._engine_status_lb.setText(tr("引擎已连接"))
            self._refresh_engine_btn.setVisible(False)  # 已连接 → 藏起刷新按钮
        elif state == "busy":
            self._engine_dot.setStyleSheet("color:#E6A23C;")
            self._engine_status_lb.setText(tr("引擎刷新中…"))
            self._refresh_engine_btn.setVisible(True)   # 刷新中 → 可见（禁用由 _on_refresh_engine 管）
        else:
            self._engine_dot.setStyleSheet("color:#AA3333;")
            # 首启 dsh 冷启动（3 万文件 + 杀软首扫）可能超 180 秒 → 状态灯显示未连接，但 dsh
            # 进程仍在后台继续启动（dsh_launcher 超时后保留进程 + 记录端口）。点「刷新」重新
            # 探测/拉起，等 dsh 热了就接上，不用重启电脑。旧版「重启电脑后再试」的真根因是
            # 安装器 RedirectionGuard 拦 junction（setup.iss 已 RedirectionGuard=no），已修掉。
            self._engine_status_lb.setText(tr("引擎未连接 · 点「刷新」重试"))
            self._refresh_engine_btn.setVisible(True)   # 未连接 → 显示刷新按钮，给用户重试入口

    # ---------- 余额（DeepSeek 账户） ----------

    def refresh_balance(self):
        """拉取 DeepSeek 余额（后台线程），结果回主线程刷新显示。
        没配 Key 显示「未配置」；请求失败显示「查询失败」，点击可重试。"""
        key = ""
        try:
            key = self._settings.deepseek_api_key or ""
        except Exception:
            key = ""
        if not key:
            self._set_balance(tr("余额：未配置"))
            return
        self._balance_btn.setEnabled(False)
        self._balance_btn.setText(tr("余额：查询中…"))
        import threading
        threading.Thread(target=self._run_balance_fetch, args=(key,), daemon=True).start()

    def _run_balance_fetch(self, key: str):
        """后台线程：用 Key 调余额接口，结果（或错误）通过信号回主线程。"""
        try:
            from tamias.api.deepseek_api import DeepSeekAPI
            api = DeepSeekAPI(api_key=key, api_base=self._settings.deepseek_api_base)
            info = api.get_balance()
            symbol = {"CNY": "¥", "USD": "$"}.get(
                info.get("currency", "CNY"), info.get("currency", ""))
            text = tr("余额 {} {:.2f}", symbol, info.get("total_balance", 0))
        except Exception:
            text = tr("余额：查询失败")
        self._balance_fetched.emit(text)

    def _on_balance_fetched(self, text: str):
        """余额拉取完成（主线程）：恢复按钮 + 更新显示。"""
        self._balance_btn.setEnabled(True)
        self._set_balance(text)

    def _set_balance(self, text: str):
        self._balance_btn.setText(text)

    # ---------- 工作目录 ----------

    def set_work_dir(self, path: str):
        """工作目录变了：刷新文件树根 + 状态条路径。
        「打开文件夹」传了具体路径就用它；空值退回项目根目录（代码/文档都在那，方便预览）。"""
        wd = path or ""
        if not wd:
            wd = self._file_page._resolve_work_dir()
        self._file_page.set_root(wd)
        # 路径太长就截断显示，完整路径挂 tooltip
        shown = wd
        if len(shown) > 28:
            shown = "…" + shown[-27:]
        self._work_dir_lb.setText(shown)
        self._work_dir_lb.setToolTip(wd)

    def set_conversations(self, convs, current_id: str = "", project_name: str = ""):
        """把「当前项目」的对话列表推给「对话」标签页（由 ChatDialog 调用）。"""
        self._conv_page.set_conversations(convs, current_id, project_name)

    # ---------- 主题 ----------

    def _palette(self) -> dict:
        """深色/暖棕双调色板（与 chat_dialog._apply_panel_theme 同源，保持视觉统一）。
        值从 theme.py 色板取，这里只做「面板语义 key → 色板 key」的映射。"""
        if self._dark:
            c = DARK
            return dict(
                bar_bg=c["panel"], text=c["text"], dim=c["muted"], border=c["divider"],
                border2=c["border"], accent=c["success"], btn=c["card"],
                hover=c["hover_bg"], pane_bg=c["bg"], tab_sel=c["bg"],
            )
        c = WARM
        return dict(
            bar_bg=c["card"], text=c["text"], dim=c["title"], border=c["divider"],
            border2=c["border"], accent=c["primary"], btn=c["card"],
            hover=c["bg"], pane_bg=c["card"], tab_sel=c["card"],
        )

    def _apply_icons(self):
        """给回滚按钮 + 四个标签页上 Lucide 图标（随主题深浅上色）。"""
        self._rollback_btn.setIcon(icon("undo-2", 14, self._dark))
        self._tabs.setTabIcon(0, icon("folder", 16, self._dark))
        self._tabs.setTabIcon(1, icon("message-circle", 16, self._dark))
        self._tabs.setTabIcon(2, icon("file-text", 16, self._dark))
        self._tabs.setTabIcon(3, icon("scroll-text", 16, self._dark))
        self._tabs.setTabIcon(4, icon("book", 16, self._dark))

    def apply_theme(self, dark: bool):
        """随专业模式主题切深色/暖棕：状态条 + 标签页 + 三个子页一次刷新。"""
        self._dark = dark
        self._apply_icons()
        p = self._palette()

        # 状态条背景 + 状态文字 + 工作目录
        self.setStyleSheet(f"ViewerPanel {{ background:{p['bar_bg']}; }}")
        self._engine_status_lb.setStyleSheet(f"color:{p['dim']};")
        self._work_dir_lb.setStyleSheet(f"color:{p['dim']};")
        self._refresh_engine_btn.setStyleSheet(
            f"QPushButton{{background:{p['btn']};color:{p['dim']};border:1px solid {p['border2']};"
            f"border-radius:3px;padding:3px 10px;}}"
            f"QPushButton:hover{{background:{p['hover']};color:{p['accent']};}}")
        self._rollback_btn.setStyleSheet(
            f"QPushButton{{background:{p['btn']};color:{p['dim']};border:1px solid {p['border2']};"
            f"border-radius:3px;padding:3px 10px;}}"
            f"QPushButton:hover{{background:{p['hover']};color:{p['accent']};}}")
        self._balance_btn.setStyleSheet(
            f"QPushButton{{background:{p['btn']};color:{p['accent']};border:1px solid {p['border2']};"
            f"border-radius:3px;padding:3px 8px;}}"
            f"QPushButton:hover{{background:{p['hover']};}}"
            f"QPushButton:disabled{{color:{p['dim']};}}")

        # 标签页
        if dark:
            self._tabs.setStyleSheet(
                f"QTabWidget::pane{{border:1px solid {p['border']};background:{p['pane_bg']};}}"
                f"QTabBar::tab{{background:{p['bar_bg']};color:{p['dim']};padding:6px 12px;"
                f"border:1px solid {p['border']};}}"
                f"QTabBar::tab:selected{{background:{p['tab_sel']};color:{p['accent']};"
                f"border-bottom:2px solid {p['accent']};}}")
        else:
            self._tabs.setStyleSheet(
                f"QTabWidget::pane{{border:1px solid {p['border']};background:{p['pane_bg']};}}"
                f"QTabBar::tab{{background:{p['hover']};color:{p['dim']};padding:6px 12px;"
                f"border:1px solid {p['border']};}}"
                f"QTabBar::tab:selected{{background:{p['tab_sel']};color:{p['accent']};"
                f"border-bottom:2px solid {p['accent']};}}")

        # 五个子页
        self._file_page.apply_theme(dark)
        self._conv_page.apply_theme(dark)
        self._log_page.apply_theme(dark)
        self._doc_page.apply_theme(dark)
        self._mem_page.apply_theme(dark)


# ============================================================
# 模块级测试（单独开面板看三个 tab + 主题切换）
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    # 造一个假 settings：resolve_work_dir 返回当前目录，方便看文件树
    class _FakeSettings:
        def resolve_work_dir(self):
            return os.getcwd()
    panel = ViewerPanel(_FakeSettings())
    panel.apply_theme(False)  # 暖棕
    panel.resize(560, 640)
    panel.show()
    print("查看器面板已打开（暖棕）；改成 dark 看深色，可自行调 apply_theme(True)")
    sys.exit(app.exec())
