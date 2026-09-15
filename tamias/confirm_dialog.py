# ============================================================
# 栗栗（Tamias）— 二次元确认弹窗
# ============================================================
# 当干活引擎需要执行系统操作时弹出的确认窗口。
# 颜色用普通模式暖色系（跟聊天界面一致，临时配色，人设定稿后再统一）。
# 用户可以看到操作详情，选择批准或拒绝。
# ============================================================

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QWidget, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from tamias.i18n import tr
from tamias.fonts import ui_font, mono_font
from tamias.ui_icons import apply_icon, strip_leading_emoji


# ---------- 常量 ----------

DIALOG_WIDTH = 420
DIALOG_HEIGHT = 440

# 颜色主题（普通模式暖色系，跟 chat_dialog 聊天界面对齐；人设定稿后再统一）
COLOR_BG = "#F5EDE1"          # 背景（暖羊皮纸米白）
COLOR_BORDER = "#C7A27E"      # 边框（浅暖棕）
COLOR_APPROVE = "#A9745B"     # 批准按钮（栗棕/焦糖，栗栗主色）
COLOR_APPROVE_HOVER = "#8A5F49"   # 批准按钮 hover（深栗）
COLOR_APPROVE_PRESSED = "#6E4A38"  # 批准按钮 pressed（更深栗）
COLOR_DENY_BG = "#FFFDF7"     # 拒绝按钮背景（暖奶白）
COLOR_DENY_TEXT = "#463329"   # 拒绝按钮文字（深咖）
COLOR_DENY_BORDER = "#C7A27E"  # 拒绝按钮边框（浅暖棕）
COLOR_TITLE = "#7A5540"       # 标题（暖棕）
COLOR_DETAIL_BG = "#FFFDF7"   # 详情背景（暖奶白）
COLOR_TEXT = "#463329"        # 正文（深咖）
COLOR_TEXT_DIM = "#A98B6D"    # 次要文字（浅暖棕）


class ConfirmDialog(QDialog):
    """
    二次元确认弹窗
    -------------
    当栗栗需要执行系统操作时弹出。
    显示操作描述，提供批准/拒绝按钮。

    使用方式：
        dialog = ConfirmDialog(
            title="启动AI干活助手",
            description="栗栗想帮你写一个Python脚本...",
            details="将执行：创建文件 /tmp/test.py",
            parent=pet_window
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 用户批准
            ...
    """

    # 信号：用户做出决定后发出
    decided = Signal(bool)  # True=批准, False=拒绝

    def __init__(self,
                 title: str = "",
                 description: str = "",
                 details: str = "",
                 parent=None):
        """
        Args:
            title: 弹窗标题（简短，如"启动AI干活助手"）
            description: 操作描述（一两句话说明）
            details: 操作详情（列出具体操作）
            parent: 父窗口
        """
        super().__init__(parent)

        self._title_text = title or tr("栗栗确认")
        self._description = description
        self._details = details
        self._result = False  # 用户选择

        # ---------- 窗口设置 ----------
        self.setWindowTitle(tr("栗栗确认"))
        self.setFixedSize(DIALOG_WIDTH, DIALOG_HEIGHT)

        # 非模态，不阻塞聊天窗口
        self.setWindowModality(Qt.WindowModality.NonModal)

        # 去掉问号按钮（setWindowFlag 精确关一个 flag，避免 &~ 在 PySide6 下误删 X 关闭按钮）
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        # 背景样式
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_BG};
                border: 2px solid {COLOR_BORDER};
                border-radius: 4px;
            }}
        """)

        # ---------- 构建 UI ----------
        self._init_ui()

        # 全局快捷键 1=批准 / 2=拒绝。弹窗是非模态的，焦点常还停在聊天输入框，
        # 光靠 keyPressEvent 只在弹窗自己有焦点时才触发，用户按 1/2 会打进输入框
        # 而不是批准。用 ApplicationShortcut 让 1/2 在整个应用范围生效，不管焦点
        # 在哪都能批；QShortcut 父对象绑 self，弹窗一关快捷键随之失效，不残留。
        self._sc_approve = QShortcut(QKeySequence("1"), self)
        self._sc_approve.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_approve.activated.connect(self._on_approve)
        self._sc_deny = QShortcut(QKeySequence("2"), self)
        self._sc_deny.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_deny.activated.connect(self._on_deny)

        # ---------- 定位到父窗口附近 ----------
        self._position_near_parent()

    def _init_ui(self):
        """构建 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(10)

        # --- 标题 ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        # 标题文字（居中；栗栗正式立绘还没做，暂不放头像）
        title_label = QLabel(f"「{self._title_text}」")
        title_font = ui_font(13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {COLOR_TITLE};")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title_label, stretch=1)

        main_layout.addLayout(header_layout)

        # --- 分隔线 ---
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; border-radius: 1px;")
        main_layout.addWidget(sep)

        # --- 内容区（描述 + 详情，统一可滚动） ---
        # 之前描述文字直接放主布局（无滚动）、详情单独一个小滚动区（最高 100px），
        # 当描述/详情很长时，固定高度窗口被内容撑爆，底部「批准/拒绝」按钮被挤出可视区，
        # 用户得先滚到最下面才能按。改成描述+详情合并进一个滚动区，按钮固定在底部永远可见。
        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: #C7A27E;
                border-radius: 3px;
            }}
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet(f"background-color: {COLOR_BG};")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # 描述文字
        if self._description:
            desc_label = QLabel(self._description)
            desc_label.setWordWrap(True)
            desc_font = ui_font(10)
            desc_label.setFont(desc_font)
            desc_label.setStyleSheet(f"color: {COLOR_TEXT}; padding: 5px;")
            content_layout.addWidget(desc_label)

        # 操作详情
        if self._details:
            detail_title = QLabel(strip_leading_emoji(tr("📋 操作详情：")))
            detail_title.setFont(ui_font(9))
            detail_title.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-weight: bold;")
            content_layout.addWidget(detail_title)

            detail_label = QLabel(self._details)
            detail_label.setWordWrap(True)
            detail_label.setFont(mono_font(9))
            detail_label.setStyleSheet(f"""
                background-color: {COLOR_DETAIL_BG};
                color: {COLOR_TEXT};
                padding: 8px;
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
            """)
            detail_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            content_layout.addWidget(detail_label)

        content_layout.addStretch(1)
        content_scroll.setWidget(content_widget)
        main_layout.addWidget(content_scroll, stretch=1)

        # --- 栗栗的提示语 ---
        hint_label = QLabel(tr("栗栗：这个操作要执行吗？(。・ω・。)"))
        hint_font = ui_font(10)
        hint_label.setFont(hint_font)
        hint_label.setStyleSheet(f"color: {COLOR_TEXT}; padding: 10px 0;")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(hint_label)

        # --- 按钮区 ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)

        # 批准按钮
        approve_btn = apply_icon(QPushButton(), "circle-check", f"{tr('✅  批准执行')}  (1)")
        approve_btn.setMinimumHeight(45)
        approve_font = ui_font(11)
        approve_font.setBold(True)
        approve_btn.setFont(approve_font)
        approve_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_APPROVE};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_APPROVE_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_APPROVE_PRESSED};
            }}
        """)
        approve_btn.clicked.connect(self._on_approve)
        button_layout.addWidget(approve_btn)

        # 拒绝按钮
        deny_btn = apply_icon(QPushButton(), "circle-x", f"{tr('❌  拒绝')}  (2)")
        deny_btn.setMinimumHeight(45)
        deny_font = ui_font(11)
        deny_btn.setFont(deny_font)
        deny_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_DENY_BG};
                color: {COLOR_DENY_TEXT};
                border: 1px solid {COLOR_DENY_BORDER};
                border-radius: 4px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: #F5EDE1;
            }}
            QPushButton:pressed {{
                background-color: #E4D3BC;
            }}
        """)
        deny_btn.clicked.connect(self._on_deny)
        button_layout.addWidget(deny_btn)

        main_layout.addLayout(button_layout)

    def _position_near_parent(self):
        """定位到父窗口附近"""
        parent = self.parent()
        if parent is None:
            return

        parent_geo = parent.frameGeometry()

        from PySide6.QtWidgets import QApplication
        screen = QApplication.screenAt(parent_geo.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        screen_geo = screen.availableGeometry()

        # 放在父窗口左侧
        x = parent_geo.left() - DIALOG_WIDTH - 20
        if x < screen_geo.left():
            x = parent_geo.right() + 20
            if x + DIALOG_WIDTH > screen_geo.right():
                x = screen_geo.center().x() - DIALOG_WIDTH // 2

        y = parent_geo.top() - 50
        if y < screen_geo.top():
            y = screen_geo.top() + 20
        if y + DIALOG_HEIGHT > screen_geo.bottom():
            y = screen_geo.bottom() - DIALOG_HEIGHT - 20

        self.move(int(x), int(y))

    # ---------- 按钮事件 ----------

    def _on_approve(self):
        """用户点击批准"""
        self._result = True
        self.decided.emit(True)
        self.accept()

    def _on_deny(self):
        """用户点击拒绝"""
        self._result = False
        self.decided.emit(False)
        self.reject()

    @property
    def is_approved(self) -> bool:
        """用户是否批准了操作"""
        return self._result


# ============================================================
# 便捷函数：在其他模块中快速调用确认弹窗
# ============================================================

def show_confirm(title: str, description: str,
                 details: str = "", parent=None) -> bool:
    """
    显示确认弹窗并返回用户的决定。

    Args:
        title: 标题
        description: 描述
        details: 详情
        parent: 父窗口

    Returns:
        bool: True=批准, False=拒绝
    """
    dialog = ConfirmDialog(
        title=title,
        description=description,
        details=details,
        parent=parent,
    )
    dialog.exec()
    return dialog.is_approved


# ============================================================
# 模块级测试
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    print("测试确认弹窗...")
    print("应该看到一个暖色主题（米白+栗棕）的确认窗口，无头像")

    # 测试 show_confirm 便捷函数
    result = show_confirm(
        title="启动AI干活助手",
        description="栗栗检测到你想让她帮你写代码呢！\n这是需要调用AI编程助手的任务，可能涉及文件读写等操作。",
        details="任务：帮我写一个Python脚本，计算斐波那契数列\n"
                "预计操作：\n"
                "  • 创建文件 fibonacci.py\n"
                "  • 写入约 30 行代码\n",
    )

    if result:
        print("用户点击了：批准执行")
    else:
        print("用户点击了：拒绝")

    print("测试完成！")
