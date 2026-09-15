# ============================================================
# 栗栗（Tamias）— 干活回滚对话框
# ============================================================
# 主人点「这次改了 N 个文件」后弹出的对比/撤销窗口：
#   左侧：本次任务改动的文件清单
#   右侧：选中文件「改前 / 改后」左右对比（改动行柔和标黄）
#   底部：撤销此文件 / 一键全部撤销 / 关闭
# 撤销直接拿门禁插件拍下的快照覆盖回文件（新建的则删除），
# 确定性还原、不靠模型重写，主人无需描述原文。
# 配色跟随专业模式主题：深色=终端风；暖棕=侦探风（米白底+深咖字+暖棕描边）。
# ============================================================

import difflib
import html
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QTextEdit, QPushButton, QLabel, QWidget, QMessageBox, QSplitter,
)
from PySide6.QtCore import Qt

from tamias.snapshot_store import SnapshotStore
from tamias.i18n import tr
from tamias.fonts import ui_font, mono_font


def _esc(s: str) -> str:
    return html.escape(s)


def _hl(s: str, color: str) -> str:
    """给一段文本套上柔和底色（用于改动行高亮）。"""
    return f'<span style="background:{color};">{s}</span>'


def _diff(left_text: str, right_text: str):
    """按行做「左 → 右」对比，返回 (左 html, 右 html)。
    黄色=修改、浅红=左有右无（右侧删掉）、浅绿=左无右有（右侧新增）；
    两侧用空行占位保持行对齐。"""
    left_lines = left_text.splitlines()
    right_lines = right_text.splitlines()
    sm = difflib.SequenceMatcher(None, left_lines, right_lines)
    left, right = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            left += [_esc(l) for l in left_lines[i1:i2]]
            right += [_esc(l) for l in right_lines[j1:j2]]
        elif tag == "replace":
            left += [_hl(_esc(l), "#FFF0B3") for l in left_lines[i1:i2]]
            right += [_hl(_esc(l), "#FFF0B3") for l in right_lines[j1:j2]]
        elif tag == "delete":
            left += [_hl(_esc(l), "#FFD9D9") for l in left_lines[i1:i2]]
            right += [""] * (i2 - i1)
        elif tag == "insert":
            left += [""] * (j2 - j1)
            right += [_hl(_esc(l), "#D9F2D9") for l in right_lines[j1:j2]]
    return "<br/>".join(left), "<br/>".join(right)


class RollbackDialog(QDialog):
    """干活回滚：文件清单 + 左右对比 + 单文件/全部撤销。"""

    def __init__(self, work_dir: str, parent=None, dark: bool = True):
        super().__init__(parent)
        self._work_dir = work_dir
        self._dark = dark
        self._c = self._palette()
        self._store = SnapshotStore(work_dir)
        # [{hash, path, saved_at, existed_before}]，撤销后从里删掉，保持清单与 manifest 同步
        self._snapshots = self._store.list_snapshots()

        self.setWindowTitle(tr("干活回滚"))
        # 模态作用域收敛：exec() 默认 ApplicationModal 会把同应用所有顶层窗口
        # （含置顶的栗栗）一起禁掉 → 栗栗盖在回滚窗上又拖不动。改成 WindowModal
        # 只禁用父窗口（聊天框），栗栗（独立顶层置顶窗口）仍可拖动、可挪开。
        self.setWindowModality(Qt.WindowModality.WindowModal)
        # 回滚窗自身也置顶：打开时盖过栗栗，避免栗栗在 Z 序上挡住对比界面。
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(1080, 640)
        self._build_ui()
        self._refresh_list()

    # ---------- 配色 ----------

    def _palette(self) -> dict:
        """返回主题色板。深色=终端风；暖棕=侦探风（米白底+深咖字+暖棕描边）。"""
        if self._dark:
            return {
                "dialog_bg": "#151515",
                "title": "#CCCCCC",
                "hint": "#888888",
                "list_title": "#AAAAAA",
                "list_bg": "#0D0D0D",
                "list_border": "#333333",
                "list_text": "#CCCCCC",
                "list_item_border": "#222222",
                "list_selected_bg": "#1A3A3A",
                "list_selected_text": "#FFFFFF",
                "view_bg": "#0D0D0D",
                "view_text": "#CCCCCC",
                "view_border": "#333333",
                "btn_bg": "#1A1A1A",
                "btn_text": "#CCCCCC",
                "btn_border": "#444444",
                "close_text": "#888888",
                "close_hover_bg": "#333333",
                "close_hover_text": "#CCCCCC",
            }
        return {
            "dialog_bg": "#F5EDE1",
            "title": "#7A5540",
            "hint": "#B07B50",
            "list_title": "#7A5540",
            "list_bg": "#FFFDF7",
            "list_border": "#E4D3BC",
            "list_text": "#463329",
            "list_item_border": "#F0E4D2",
            "list_selected_bg": "#EBDCC8",
            "list_selected_text": "#463329",
            "view_bg": "#FFFDF7",
            "view_text": "#463329",
            "view_border": "#E4D3BC",
            "btn_bg": "#FFFDF7",
            "btn_text": "#7A5540",
            "btn_border": "#C7A27E",
            "close_text": "#B07B50",
            "close_hover_bg": "#F0E4D2",
            "close_hover_text": "#7A5540",
        }

    # ---------- UI 构建 ----------

    def _build_ui(self):
        c = self._c
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 标题 + 说明
        self._title_lb = QLabel(tr("干活回滚"))
        self._title_lb.setFont(ui_font(16, bold=True))
        self._title_lb.setStyleSheet(f"color:{c['title']};")
        root.addWidget(self._title_lb)
        self._hint_lb = QLabel(tr("栗栗改动过的文件都在下面，点左侧文件看现在/撤销后对比，可逐个撤销或一键全部撤销。"))
        self._hint_lb.setFont(ui_font(11))
        self._hint_lb.setWordWrap(True)
        self._hint_lb.setStyleSheet(f"color:{c['hint']};")
        root.addWidget(self._hint_lb)

        # 左右分栏：文件清单 | 对比视图
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：文件清单
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self._list_title = QLabel(tr("改动的文件"))
        self._list_title.setFont(ui_font(11, bold=True))
        self._list_title.setStyleSheet(f"color:{c['list_title']};")
        left_layout.addWidget(self._list_title)
        self._file_list = QListWidget()
        self._file_list.setStyleSheet(
            f"QListWidget{{background:{c['list_bg']};border:1px solid {c['list_border']};color:{c['list_text']};font-size:12px;}}"
            f"QListWidget::item{{padding:6px;border-bottom:1px solid {c['list_item_border']};}}"
            f"QListWidget::item:selected{{background:{c['list_selected_bg']};color:{c['list_selected_text']};}}"
        )
        self._file_list.currentItemChanged.connect(self._on_select_file)
        left_layout.addWidget(self._file_list, stretch=1)
        splitter.addWidget(left_widget)

        # 右：现在 / 撤销后对比
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        headers = QHBoxLayout()
        self._current_lb = QLabel(tr("现在"))
        self._restored_lb = QLabel(tr("撤销后"))
        for lb, color in ((self._current_lb, "#E6A23C"), (self._restored_lb, "#67C23A")):
            lb.setFont(ui_font(11, bold=True))
            lb.setStyleSheet(f"color:{color};")
            headers.addWidget(lb, stretch=1)
        right_layout.addLayout(headers)

        diff_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._current_view = self._make_view()   # 左：现在（当前文件）
        self._restored_view = self._make_view()  # 右：撤销后（快照原文）
        diff_splitter.addWidget(self._current_view)
        diff_splitter.addWidget(self._restored_view)
        right_layout.addWidget(diff_splitter, stretch=1)
        splitter.addWidget(right_widget)

        splitter.setSizes([360, 720])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, stretch=1)

        # 底部按钮
        btns = QHBoxLayout()
        btns.addStretch()
        self._restore_btn = QPushButton(tr("↩ 撤销此文件"))
        self._restore_btn.setEnabled(False)
        self._restore_btn.setFont(ui_font(11, bold=True))
        self._restore_btn.setStyleSheet(
            f"QPushButton{{background:{c['btn_bg']};color:{c['btn_text']};border:1px solid {c['btn_border']};border-radius:4px;padding:10px 16px;}}"
            "QPushButton:enabled{background:#B07B50;color:#FFFFFF;border-color:#B07B50;}"
            "QPushButton:enabled:hover{background:#C08A5F;}"
        )
        self._restore_btn.clicked.connect(self._on_restore_one)
        btns.addWidget(self._restore_btn)

        self._restore_all_btn = QPushButton(tr("↩↩ 一键全部撤销"))
        self._restore_all_btn.setFont(ui_font(11, bold=True))
        self._restore_all_btn.setStyleSheet(
            f"QPushButton{{background:{c['btn_bg']};color:{c['btn_text']};border:1px solid {c['btn_border']};border-radius:4px;padding:10px 16px;}}"
            "QPushButton:enabled{background:#AA3333;color:#FFFFFF;border-color:#AA3333;}"
            "QPushButton:enabled:hover{background:#CC4444;}"
        )
        self._restore_all_btn.clicked.connect(self._on_restore_all)
        btns.addWidget(self._restore_all_btn)

        self._close_btn = QPushButton(tr("关闭"))
        self._close_btn.setFont(ui_font(11))
        self._close_btn.setStyleSheet(
            f"QPushButton{{background:{c['btn_bg']};color:{c['close_text']};border:1px solid {c['btn_border']};border-radius:4px;padding:10px 16px;}}"
            f"QPushButton:hover{{background:{c['close_hover_bg']};color:{c['close_hover_text']};}}"
        )
        self._close_btn.clicked.connect(self.accept)
        btns.addWidget(self._close_btn)
        root.addLayout(btns)

        self.setStyleSheet(f"QDialog{{background:{c['dialog_bg']};}}")

    def _make_view(self) -> QTextEdit:
        c = self._c
        v = QTextEdit()
        v.setReadOnly(True)
        v.setFont(mono_font(9))
        v.setStyleSheet(
            f"QTextEdit{{background:{c['view_bg']};color:{c['view_text']};border:1px solid {c['view_border']};padding:6px;}}"
        )
        return v

    # ---------- 清单 / 对比 ----------

    def _refresh_list(self):
        """重建文件清单（撤销后调用）。"""
        self._file_list.clear()
        for snap in self._snapshots:
            path = snap["path"]
            try:
                rel = os.path.relpath(path, self._work_dir)
            except ValueError:
                rel = path
            display = rel if not rel.startswith("..") else path
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, snap["hash"])
            item.setToolTip(path)
            self._file_list.addItem(item)
        count = len(self._snapshots)
        self._list_title.setText(tr("改动的文件（{}）", count))
        if count == 0:
            self._current_view.clear()
            self._restored_view.clear()
            self._restore_btn.setEnabled(False)
            self._restore_all_btn.setEnabled(False)
        else:
            self._restore_all_btn.setEnabled(True)

    def _on_select_file(self, current, _previous):
        """选中某个文件 → 加载「现在 / 撤销后」内容并渲染对比。"""
        if current is None:
            return
        fp = current.data(Qt.ItemDataRole.UserRole)
        snap = next((s for s in self._snapshots if s["hash"] == fp), None)
        if snap is None:
            return
        # 撤销视角：左=现在（当前文件）、右=撤销后（快照原文）。
        # _diff(左, 右) 标红「左有右无」=撤销会删掉的（栗栗新增）；标绿「左无右有」=撤销会找回的（栗栗删除）。
        current_text = self._store.read_after(snap["path"])
        restored_text = self._store.read_before(fp)
        left_html, right_html = _diff(current_text, restored_text)
        self._current_view.setHtml(left_html or "")
        self._restored_view.setHtml(right_html or "")
        self._restore_btn.setEnabled(True)

    # ---------- 撤销 ----------

    def _on_restore_one(self):
        """撤销当前选中的文件。"""
        current = self._file_list.currentItem()
        if current is None:
            return
        fp = current.data(Qt.ItemDataRole.UserRole)
        snap = next((s for s in self._snapshots if s["hash"] == fp), None)
        if snap is None:
            return
        # 确认：还原是不可逆的（会丢掉当前改动），让主人明确点一次
        confirm = QMessageBox.question(
            self, tr("撤销改动"),
            tr("确定要把这个文件还原到栗栗改动之前吗？\n当前内容会被覆盖，无法找回。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self._store.restore(fp):
            self._snapshots = [s for s in self._snapshots if s["hash"] != fp]
            self._refresh_list()
            self._current_view.clear()
            self._restored_view.clear()
        else:
            QMessageBox.warning(self, tr("撤销失败"), tr("这个文件没能还原，可能已被删除或权限不足。"))

    def _on_restore_all(self):
        """一键全部撤销。"""
        n = len(self._snapshots)
        confirm = QMessageBox.question(
            self, tr("一键全部撤销"),
            tr("确定要把本次任务改动的 {} 个文件全部还原吗？\n这些改动会一起被覆盖，无法找回。", n),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok, fail = self._store.restore_all()
        self._snapshots = []
        self._refresh_list()
        self._current_view.clear()
        self._restored_view.clear()
        if fail:
            QMessageBox.warning(self, tr("部分撤销"), tr("成功还原 {} 个文件，{} 个失败。", ok, fail))
        else:
            QMessageBox.information(self, tr("已全部撤销"), tr("本次任务的 {} 个改动已全部还原。", ok))
