# ============================================================
# 栗栗（Tamias）— 协议 / 隐私政策查看器
# ============================================================
# 把 docs/legal/ 下的《用户协议》《隐私政策》渲染成可滚动阅读的
# 对话框。合规要求（《暂行办法》/《个人信息保护法》）：用户必须能
# 「随时回看」已经同意的条款，所以右键设置里要留入口。
#
# 文档本身是 Markdown，Qt 的 QTextBrowser.setMarkdown() 直接支持，
# 标题 / 加粗 / 表格 / 列表都能正常渲染，不用自己写转换器。
# ============================================================

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton

from tamias.i18n import tr
from tamias.fonts import ui_font


# 协议文档目录：项目根/docs/legal/（打包时需把 docs/legal/ 一起带上）
LEGAL_DIR = Path(__file__).resolve().parent.parent / "docs" / "legal"

# 文档名（中文原文 = i18n key） → 相对 LEGAL_DIR 的文件名
LEGAL_FILES = {
    "用户协议": "用户协议.md",
    "隐私政策": "隐私政策.md",
}


class LegalTextViewer(QDialog):
    """协议 / 隐私政策阅读对话框：可滚动、可选中复制。"""

    def __init__(self, title: str, markdown: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr(title))
        self.resize(600, 680)
        self.setStyleSheet("""
            QDialog { background: #F5EDE1; }
            QTextBrowser {
                background: #FFFFFF;
                border: 1px solid #C7A27E;
                border-radius: 6px;
                color: #463329;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 正文：Markdown 渲染成富文本，支持滚动 + 鼠标选中复制
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setMarkdown(markdown)
        layout.addWidget(self._browser)

        # 关闭按钮
        close_btn = QPushButton(tr("关闭"))
        close_btn.setFont(ui_font(11))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #A9745B;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 8px 24px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background: #9A6550; }
        """)
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


def show_legal_text(title: str, parent=None):
    """打开《用户协议》或《隐私政策》阅读对话框。

    Args:
        title: 文档名（中文原文当 i18n key，如「用户协议」「隐私政策」）。
        parent: 父窗口（设置窗等），用于对话框定位。
    """
    filename = LEGAL_FILES.get(title)
    path = LEGAL_DIR / filename if filename else None
    if path is not None and path.exists():
        try:
            markdown = path.read_text(encoding="utf-8")
        except Exception:
            markdown = tr("文档读取失败：{}", str(path))
    else:
        markdown = tr("文档缺失：{}", str(path) if path else title)
    dlg = LegalTextViewer(title, markdown, parent=parent)
    dlg.exec()
