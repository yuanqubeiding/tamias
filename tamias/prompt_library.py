# ============================================================
# 栗栗（Tamias）— 专业提示词库（+ 按键说明表）
# ============================================================
# 本文件承载两件「给用户参考」的小事：
#   1. 专业提示词库：把新手用户最常用、但一时想不到怎么说的指令
#      （干活 + 反问）做成可点选的词条，点一下就填进输入框，不用
#      一个字一个字打。入口 = 输入栏旁的 💡 按钮，或快捷键 Ctrl+P。
#   2. 按键说明表 SHORTCUTS：集中一份「按键 → 作用 → 何时能用」，
#      设置页「查看按键说明」读它显示，以后加按键只改这一处。
#
# 面板键盘导航（w/s/a/d/Enter/Esc，游戏化键位，跟桌宠调性搭）：
#   w = 上移一条、s = 下移一条、a/d = 切分类、Enter = 选中填入、Esc = 关闭
# 词条按「使用频率」从高到低排：点得越多越靠前，存 config.yaml
# （prompt_lib.usage），重启不丢。
#
# 词条内容是中文指令原文，不走 i18n（这是发给 AI 的中文提示词，翻译
# 反而变味；面板标题/分类/提示等 UI 文案才走 tr，见 i18n.py「中文
# 原文当 key」兜底机制）。
# ============================================================

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem,
)

from tamias.i18n import tr
from tamias.fonts import ui_font
from tamias.ui_icons import icon, strip_leading_emoji
from tamias.theme import WARM as _C


# ---------- 词表 ----------

# 分类 key → 提示词原文。顺序 = 使用频率相同时的初始顺序。
# 「XX」是占位符，用户点选后把 XX 改成自己要的东西再发。
_PROMPTS = {
    "work": [  # 干活：栗栗真的能动手（改文件 / 整理 / 写脚本）
        "帮我整理这个文件夹，按文件类型分类",
        "把这个文件夹里的文件列个清单",
        "帮我把这些照片按日期重命名",
        "找出这个文件夹里的重复文件",
        "总结一下这个文件夹里都有什么",
        "把这个文档总结成三句话",
        "写个脚本，把这些文件批量重命名",
        "把这个文件夹里的文件按大小排序",
        "统计一下这个文件夹里各类型文件的数量",
        "帮我查一下XX的最新消息",
    ],
    "ask": [  # 反问：让栗栗先问清楚再动手（新手需求模糊时最有用）
        "你看看这个文件夹，先问问我该怎么整理",
        "先别急着动手，问我几个问题搞清楚需求",
        "我不确定要你干什么，你反问我吧",
        "帮我看看这里有什么活能交给你，问清楚再做",
    ],
}

# 分类展示顺序：key → (标签文案)。顶部两个切换标签按这个顺序排。
_CATEGORIES = [
    ("work", "🛠 干活"),
    ("ask", "❓ 反问"),
]


# ---------- 按键说明表 ----------

# 按键 → (作用, 什么时候能用)。集中一处，设置页「查看按键说明」读它显示。
# 「按键」列是通用键名，不翻译；作用/时机在设置页显示时走 tr。
SHORTCUTS = [
    ("Enter", "发送消息", "输入框"),
    ("Shift + Enter", "换行（不发送）", "输入框"),
    ("Ctrl + P", "打开提示词库", "专业模式"),
    ("按住 Alt", "说话（松手停）", "任何模式"),
    ("1", "批准", "审批卡片出现时"),
    ("2", "拒绝", "审批卡片出现时"),
    ("Esc", "终止当前任务", "忙的时候"),
]


class PromptLibraryDialog(QDialog):
    """提示词库弹窗。点选词条 → picked 信号 → 调用方填进输入框（不自动发送）。"""

    picked = Signal(str)  # 最终选中的提示词原文

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._current_cat = "work"  # 默认停在「干活」

        self.setWindowTitle(tr("栗栗 - 提示词库"))
        self.setMinimumSize(440, 420)
        self.setModal(True)
        # 暖棕侦探风背景，跟功能库 / 设置对话框统一
        self.setStyleSheet(f"QDialog {{ background: {_C['bg']}; }}")

        self._build_ui()
        self._apply_cat_style()
        self._rebuild_list()

        # 拦截面板内所有按键（w/s/Enter/Esc），不管焦点落在哪个子控件都生效——
        # 若只靠 QListWidget 的 keyPressEvent，w/s 会被它的「按字母定位」吃掉、
        # 焦点在分类标签上时又收不到按键，两头都漏。
        self.installEventFilter(self)

    def showEvent(self, event):
        """面板显示时把焦点落到词条列表。

        不这么做，焦点会默认落在第一个分类按钮（autoDefault 的 QPushButton）上：
        按 Enter 会被按钮的「默认按钮」机制拦截、变成「切换分类」而不是「填入词条」；
        上下左右键变成焦点导航、在按钮/列表间乱跳，干扰 w/s 选词。
        （提示词库 Enter 不灵 + 方向键干扰的根因）
        """
        super().showEvent(event)
        self._list.setFocus()

    # ---------- 界面搭建 ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # 标题（图标 + 文字）
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_ic = QLabel()
        title_ic.setPixmap(icon("lightbulb", 18).pixmap(18, 18))
        title_row.addWidget(title_ic)
        title = QLabel(strip_leading_emoji(tr("💡 提示词库")))
        title.setFont(ui_font(14, bold=True))
        title.setStyleSheet(f"color: {_C['title']};")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 说明
        desc = QLabel(tr("点一下，把常用的话填进输入框；可以改完再发。"))
        desc.setWordWrap(True)
        desc.setFont(ui_font(10))
        desc.setStyleSheet(f"color: {_C['text']};")
        layout.addWidget(desc)

        # 分类切换标签（干活 / 反问）
        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        self._cat_btns = {}
        for key, label in _CATEGORIES:
            b = QPushButton(tr(label))
            b.setCheckable(True)
            b.setFont(ui_font(11, bold=True))
            b.clicked.connect(lambda checked=False, k=key: self._switch_cat(k))
            cat_row.addWidget(b)
            self._cat_btns[key] = b
        cat_row.addStretch()
        layout.addLayout(cat_row)

        # 词条列表
        self._list = QListWidget()
        self._list.setFont(ui_font(11))
        self._list.setSpacing(2)
        self._list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: 1px solid {_C['border']};"
            f" border-radius: 8px; }}"
            f"QListWidget::item {{ padding: 9px 10px; color: {_C['text']}; border-radius: 6px; }}"
            f"QListWidget::item:hover {{ background: {_C['card_soft']}; }}"
            f"QListWidget::item:selected {{ background: {_C['primary']}; color: {_C['white']}; }}"
        )
        layout.addWidget(self._list, stretch=1)

        # 底部按键提示
        hint = QLabel(tr("w / s 上下移动 · a / d 切换分类 · Enter 填入 · Esc 关闭"))
        hint.setFont(ui_font(9))
        hint.setStyleSheet(f"color: {_C['muted']};")
        layout.addWidget(hint)

    # ---------- 键盘导航 ----------

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_W:
                self._move_current(-1)
                return True
            if event.key() == Qt.Key.Key_S:
                self._move_current(1)
                return True
            if event.key() == Qt.Key.Key_A:
                self._switch_cat_delta(-1)
                return True
            if event.key() == Qt.Key.Key_D:
                self._switch_cat_delta(1)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._list.currentItem()
                if item is not None:
                    self._on_picked(item.text())
                return True
            # Esc 不拦，交给 QDialog 默认行为（reject 关闭）
        return super().eventFilter(obj, event)

    def _move_current(self, delta):
        """当前行上下移一格；到顶/到底停住（不循环）。"""
        row = self._list.currentRow()
        new = row + delta
        if 0 <= new < self._list.count():
            self._list.setCurrentRow(new)

    def _switch_cat_delta(self, delta):
        """A/D 切分类：delta=-1 上一个、+1 下一个；到边界停住（不循环，跟 w/s 一致）。"""
        keys = [k for k, _ in _CATEGORIES]
        idx = keys.index(self._current_cat)
        new = idx + delta
        if 0 <= new < len(keys):
            self._switch_cat(keys[new])

    # ---------- 列表与分类 ----------

    def _switch_cat(self, key):
        self._current_cat = key
        self._apply_cat_style()
        self._rebuild_list()

    def _apply_cat_style(self):
        for key, b in self._cat_btns.items():
            checked = (key == self._current_cat)
            b.setChecked(checked)
            b.setStyleSheet(self._cat_btn_style(checked))

    @staticmethod
    def _cat_btn_style(checked):
        if checked:
            return (
                f"QPushButton {{ background: {_C['primary']}; color: {_C['white']};"
                f" border: none; border-radius: 6px; padding: 5px 14px; font-weight: bold; }}"
            )
        return (
            f"QPushButton {{ background: transparent; color: {_C['title']};"
            f" border: 1px solid {_C['border']}; border-radius: 6px; padding: 5px 14px; }}"
            f"QPushButton:hover {{ background: {_C['hover_bg']}; }}"
        )

    def _rebuild_list(self):
        """按当前分类 + 使用频率排序，重建词条列表。"""
        items = _PROMPTS.get(self._current_cat, [])
        usage = self._load_usage()
        # 次数降序；次数相同保持词表原始顺序（Python 排序是稳定的）
        ordered = sorted(items, key=lambda t: usage.get(t, 0), reverse=True)
        self._list.clear()
        for text in ordered:
            self._list.addItem(QListWidgetItem(text))
        if self._list.count():
            self._list.setCurrentRow(0)

    # ---------- 选中与频率 ----------

    def _on_picked(self, text):
        """词条被 Enter 选中：计一次使用频率 + 转发给外部 + 关闭面板。"""
        self._bump_usage(text)
        self.picked.emit(text)
        self.accept()

    def _load_usage(self):
        if self._settings is None:
            return {}
        return self._settings.get("prompt_lib.usage", {}) or {}

    def _bump_usage(self, text):
        if self._settings is None:
            return
        usage = self._load_usage()
        usage[text] = usage.get(text, 0) + 1
        self._settings.set("prompt_lib.usage", usage)


# ============================================================
# 模块级测试（只验证面板能打开、能点选，不真连聊天框）
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from tamias.settings import Settings

    app = QApplication(sys.argv)
    settings = Settings()
    dlg = PromptLibraryDialog(settings=settings)
    dlg.picked.connect(lambda t: print(f"选中提示词：{t}"))
    print("提示词库面板已打开（w/s 上下、a/d 切分类、Enter 选中、Esc 关闭）")
    dlg.exec()
    print(f"当前使用频率：{settings.get('prompt_lib.usage', {})}")
