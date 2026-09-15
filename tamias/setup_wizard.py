# ============================================================
# 栗栗（Tamias）— 首次运行配置向导
# ============================================================
# 用户首次运行时引导完成必要配置：
# 1. 欢迎页
# 2. DeepSeek API Key 输入
# 3. 完成页
# ============================================================

import os
import sys
from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap, QPainter

from tamias.i18n import tr
from tamias.fonts import ui_font, mono_font
from tamias.ui_icons import apply_icon, draw_chestnut


# ---------- 常量 ----------

WIZARD_WIDTH = 550
WIZARD_HEIGHT = 440

# 颜色（暖棕侦探风，呼应聊天普通模式：背景暖羊皮纸米白 + 栗棕按钮 + 浅暖棕描边）
COLOR_BG = "#F5EDE1"
COLOR_CHECK_OK = "#4CAF50"
COLOR_CHECK_FAIL = "#F44336"
COLOR_CHECKING = "#FF9800"


class SetupWizard(QWizard):
    """
    栗栗首次运行配置向导
    ------------------
    引导用户完成 DeepSeek API Key 的配置（Node/dsh 已随包自带，无需检测）。
    """

    def __init__(self, settings, parent=None):
        """
        Args:
            settings: Settings 实例（用于保存配置）
            parent: 父窗口
        """
        super().__init__(parent)

        self._settings = settings

        # ---------- 窗口设置 ----------
        self.setWindowTitle(tr("栗栗 - 首次配置"))
        self.setFixedSize(WIZARD_WIDTH, WIZARD_HEIGHT)

        # 去掉问号按钮（setWindowFlag 精确关一个 flag，避免 &~ 在 PySide6 下误删 X 关闭按钮）
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        # 样式（暖棕侦探风，跟聊天普通模式统一）
        self.setStyleSheet(f"""
            QWizard {{
                background-color: {COLOR_BG};
            }}
            QWizard QLabel {{
                color: #463329;
            }}
            QWizard QPushButton {{
                background-color: #A9745B;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 13px;
            }}
            QWizard QPushButton:hover {{
                background-color: #8C5E48;
            }}
            QWizard QPushButton:disabled {{
                background-color: #CCCCCC;
            }}
            QLineEdit {{
                border: 2px solid #C7A27E;
                border-radius: 6px;
                padding: 8px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: #A9745B;
            }}
        """)

        # ---------- 添加页面 ----------
        self._welcome_page = WelcomePage()
        self.addPage(self._welcome_page)

        # Node.js / Git 已随包自带（便携 node 打进安装包，回滚用拍照不用 git），
        # 无需再检测，直接从欢迎页进 Key 填写页。
        self._api_key_page = APIKeyPage(settings)
        self.addPage(self._api_key_page)

        self._finish_page = FinishPage(settings)
        self.addPage(self._finish_page)

        # ---------- 定位到屏幕中央 ----------
        self._center_on_screen()

    def _center_on_screen(self):
        """居中窗口"""
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - WIZARD_WIDTH) // 2
            y = (geo.height() - WIZARD_HEIGHT) // 2
            self.move(x, y)

# ============================================================
# 向导页面
# ============================================================

class WelcomePage(QWizardPage):
    """欢迎页面"""

    def __init__(self):
        super().__init__()
        self.setTitle(tr("欢迎来到栗栗的世界！"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        # 欢迎图标（程序绘制的小头像）
        avatar = self._draw_welcome_avatar()
        avatar_label = QLabel()
        avatar_label.setPixmap(avatar)
        avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(avatar_label)

        # 欢迎文字
        welcome_text = QLabel(
            tr(
                "你好呀！我是<b>栗栗</b>，你的松鼠侦探管家～🐿️\n\n"
                "我会住在你的桌面上，陪你聊天、帮你干活！\n\n"
                "在正式开始之前，我们需要做一些小小的配置。\n"
                "别担心，我会一步一步引导你的！"
            )
        )
        welcome_text.setWordWrap(True)
        welcome_text.setFont(ui_font(10))
        welcome_text.setStyleSheet("color: #7A5540; line-height: 1.6;")
        layout.addWidget(welcome_text)

        # 说明
        note = QLabel(
            tr(
                "📌 本向导只需要配置：\n"
                "  • DeepSeek API Key\n\n"
                "干活引擎已经随包自带，无需额外安装。\n"
                "请点击「下一步」开始～"
            )
        )
        note.setWordWrap(True)
        note.setFont(ui_font(9))
        note.setStyleSheet("color: #A98B6D;")
        layout.addWidget(note)

    def _draw_welcome_avatar(self) -> QPixmap:
        """欢迎头像：优先用栗栗图标（猎鹿帽头像），缺文件才退回画一颗栗子占位。"""
        icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon", "tamias_icon.png")
        if os.path.exists(icon_path):
            return QPixmap(icon_path).scaled(
                100, 100,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 栗子半径 38，略下沉留出顶部小蒂的空间
        draw_chestnut(painter, 50, 52, 38)
        painter.end()
        return pixmap


class APIKeyPage(QWizardPage):
    """API Key 输入页面"""

    def __init__(self, settings):
        super().__init__()
        self._settings = settings

        self.setTitle(tr("DeepSeek API Key 配置"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        desc = QLabel(
            tr(
                "栗栗的聊天功能需要 DeepSeek API Key。\n\n"
                "获取方式：\n"
                "1. 访问 <a href='https://platform.deepseek.com'>platform.deepseek.com</a>\n"
                "2. 注册账号并登录\n"
                "3. 在 API Keys 页面创建一个 Key\n"
                "4. 复制 Key 并粘贴到下方"
            )
        )
        desc.setWordWrap(True)
        desc.setOpenExternalLinks(True)
        desc.setFont(ui_font(10))
        desc.setStyleSheet("color: #7A5540;")
        layout.addWidget(desc)

        # API Key 输入框
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("sk-xxxxxxxxxxxxxxxx")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setFont(mono_font(11))
        existing_key = settings.deepseek_api_key
        if existing_key:
            self._api_key_input.setText(existing_key)
        # textChanged 会带一个 str 参数，completeChanged 是 0 参信号，用 lambda 吞掉参数避免 TypeError
        self._api_key_input.textChanged.connect(lambda _text: self.completeChanged.emit())
        layout.addWidget(self._api_key_input)

        # 显示/隐藏切换
        self._show_btn = apply_icon(QPushButton(), "eye", tr("👁 显示 Key"))
        self._show_btn.setFixedWidth(120)
        self._show_btn.setStyleSheet("""
            QPushButton {
                background-color: #E4D3BC;
                color: #7A5540;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """)
        self._show_btn.clicked.connect(self._toggle_visibility)
        layout.addWidget(self._show_btn)

        # 提示
        hint = QLabel(
            tr(
                "💡 如果暂时没有 API Key，可以先跳过这一步。\n"
                "后续可以在 config.yaml 中手动配置。"
            )
        )
        hint.setWordWrap(True)
        hint.setFont(ui_font(9))
        hint.setStyleSheet("color: #A98B6D;")
        layout.addWidget(hint)

        layout.addStretch()

    def _toggle_visibility(self):
        """切换 Key 显示/隐藏"""
        if self._api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self._api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            apply_icon(self._show_btn, "eye-off", tr("🙈 隐藏 Key"))
        else:
            self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            apply_icon(self._show_btn, "eye", tr("👁 显示 Key"))

    def get_api_key(self) -> str:
        """获取用户输入的 API Key"""
        return self._api_key_input.text().strip()

    def isComplete(self) -> bool:
        """API Key 非空或允许跳过"""
        return True  # 允许跳过


class FinishPage(QWizardPage):
    """完成页面"""

    def __init__(self, settings):
        super().__init__()
        self._settings = settings
        self.setTitle(tr("配置完成！"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        # 总结
        self._summary_label = QLabel(tr("正在汇总配置..."))
        self._summary_label.setWordWrap(True)
        self._summary_label.setFont(ui_font(10))
        self._summary_label.setStyleSheet("color: #7A5540;")
        layout.addWidget(self._summary_label)

        layout.addStretch()

    def initializePage(self):
        """页面显示时生成配置摘要并保存"""
        wizard = self.wizard()

        # 收集页面结果（Node/dsh 已随包自带，只收集 Key）
        api_key = wizard._api_key_page.get_api_key()

        # 保存 API Key
        if api_key:
            self._settings.deepseek_api_key = api_key

        # 标记首次运行完成
        self._settings.is_first_run = False

        # 生成摘要
        def status_icon(ok):
            return "✅" if ok else "⚠️"

        key_status = tr("已配置") if api_key else tr("未配置")
        summary = (
            tr("配置已保存！\n\n")
            + f"{status_icon(bool(api_key))} DeepSeek API Key：{key_status}\n\n"
            + tr("干活引擎已随包自带，无需额外安装。\n\n")
            + tr("干活引擎首次启用时，若显示「未连接」，点一下「刷新」按钮即可连上。\n\n")
            + tr("点击「完成」开始和栗栗互动吧！")
        )
        self._summary_label.setText(summary)


# ============================================================
# 模块级测试
# ============================================================
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from tamias.settings import Settings

    app = QApplication(sys.argv)

    # 确保首次运行标记为 True
    settings = Settings()
    settings.is_first_run = True

    wizard = SetupWizard(settings)

    print("启动配置向导...")
    print("你应该能看到一个暖棕侦探风的配置向导窗口")

    # 显示向导
    if wizard.exec() == QWizard.DialogCode.Accepted:
        print("向导完成！")
        print(f"API Key 已保存：{bool(settings.deepseek_api_key)}")
        print(f"首次运行标记：{settings.is_first_run}")
    else:
        print("向导被取消")

    print("测试完成！")
