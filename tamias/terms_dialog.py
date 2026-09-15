# ============================================================
# 栗栗（Tamias）— 首次启动「勾选同意」弹窗
# ============================================================
# 合规要求：协议要生效，必须在首次启动时让用户「明确同意」，否则
# 免责、仲裁、责任上限这些关键条款对用户没有约束力。所以首次启动
# 弹这个窗：勾选「已阅读并同意」才能点「同意并继续」；没勾 / 直接
# 关窗 / 点「不同意」都视为拒绝，栗栗退出、不进主界面。
#
# 同意状态写进 config.yaml 的 agreed_terms 字段（见 settings.py），
# 勾一次以后不再弹。这里只负责弹窗 + 返回同意与否，落盘由 main.py 做。
# ============================================================

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QCheckBox, QPushButton)

from tamias.i18n import tr
from tamias.fonts import ui_font
from tamias.ui_icons import apply_icon, strip_leading_emoji
from tamias.legal_viewer import show_legal_text


class _ConsentDialog(QDialog):
    """首次启动同意协议弹窗。self.agreed 记录用户是否勾选同意。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.agreed = False

        self.setWindowTitle(tr("用户协议与隐私政策"))
        self.setFixedWidth(430)
        # 去掉右上角「?」帮助按钮（setWindowFlag 精确关一个 flag，避免 &~ 在 PySide6 下误删 X）
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet("""
            QDialog { background: #F5EDE1; border: 2px solid #C7A27E; }
            QLabel { color: #463329; }
            QCheckBox { color: #463329; font-size: 13px; }
            QCheckBox::indicator {
                width: 18px; height: 18px;
                background: #FFFFFF; border: 1px solid #C7A27E;
            }
            QCheckBox::indicator:checked {
                background: #A9745B; border-color: #A9745B;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel(tr("欢迎使用栗栗（Tamias）"))
        tf = ui_font(15); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet("color: #7A5540;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 说明
        intro = QLabel(tr("在开始使用前，请阅读并同意以下内容："))
        intro.setFont(ui_font(11))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # 两个查看入口：点开读全文
        view_row = QHBoxLayout()
        for doc_name in ("用户协议", "隐私政策"):
            btn_text = "📄 用户协议" if doc_name == "用户协议" else "🔒 隐私政策"
            btn = apply_icon(QPushButton(), "file-text" if doc_name == "用户协议" else "lock", tr(btn_text))
            btn.setFont(ui_font(11))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #FFFFFF; color: #7A5540;
                    border: 1px solid #C7A27E; border-radius: 8px;
                    padding: 8px; font-size: 13px;
                }
                QPushButton:hover { background: #EDE0CC; }
            """)
            btn.clicked.connect(lambda _=False, d=doc_name: show_legal_text(d, parent=self))
            view_row.addWidget(btn)
        layout.addLayout(view_row)

        # 未成年人红线提示（《暂行办法》硬性要求，醒目提醒）
        minor_note = QLabel(tr("⚠️ 本软件不面向未成年人：未满 18 周岁请在监护人同意和指导下使用，未满 14 周岁禁止使用。"))
        minor_note.setFont(ui_font(9))
        minor_note.setStyleSheet("color: #A9745B;")
        minor_note.setWordWrap(True)
        layout.addWidget(minor_note)

        # 年龄声明（《暂行办法》/未成年人保护：萌系桌宠最怕踩「向未成年提供虚拟亲密」红线，
        # 让用户主动确认年龄，实打实证明未成年人保护到位）
        self._age_check = QCheckBox(tr("我已年满 18 周岁"))
        self._age_check.setFont(ui_font(11))
        layout.addWidget(self._age_check)

        # 勾选同意协议 + 隐私政策
        self._agree_check = QCheckBox(tr("我已阅读并同意《用户协议》和《隐私政策》"))
        self._agree_check.setFont(ui_font(11))
        layout.addWidget(self._agree_check)

        # 两个勾选都打上才允许继续（先建控件再连信号，避免回调里引用还没建的控件）
        self._age_check.toggled.connect(self._on_check_toggled)
        self._agree_check.toggled.connect(self._on_check_toggled)

        # 按钮：同意并继续（勾选后才可用） + 不同意退出
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._disagree_btn = QPushButton(tr("不同意并退出"))
        self._disagree_btn.setFont(ui_font(11))
        self._disagree_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._disagree_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #A9745B;
                border: 1px solid #C7A27E; border-radius: 8px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background: #EDE0CC; }
        """)
        self._disagree_btn.clicked.connect(self._on_disagree)
        btn_row.addWidget(self._disagree_btn)

        self._agree_btn = QPushButton(tr("同意并继续"))
        self._agree_btn.setFont(ui_font(11))
        self._agree_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._agree_btn.setStyleSheet("""
            QPushButton {
                background: #A9745B; color: #FFFFFF;
                border: none; border-radius: 8px;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background: #9A6550; }
            QPushButton:disabled { background: #C7A27E; color: #F5EDE1; }
        """)
        self._agree_btn.setEnabled(False)  # 未勾选前不可点
        self._agree_btn.clicked.connect(self._on_agree)
        btn_row.addWidget(self._agree_btn)
        layout.addLayout(btn_row)

    def _on_check_toggled(self, checked: bool):
        """年龄 + 协议两个勾选都打上，才允许点「同意并继续」。"""
        self._agree_btn.setEnabled(
            self._age_check.isChecked() and self._agree_check.isChecked()
        )

    def _on_agree(self):
        self.agreed = True
        self.accept()

    def _on_disagree(self):
        self.agreed = False
        self.reject()


def show_terms_consent(parent=None) -> bool:
    """首次启动勾选同意弹窗。返回 True=用户勾选同意，False=拒绝/关闭。"""
    dlg = _ConsentDialog(parent)
    dlg.exec()
    return dlg.agreed
