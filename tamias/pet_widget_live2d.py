# ============================================================
# 栗栗（Tamias）— Live2D 角色控件
# ============================================================
# 用 QWebEngineView 嵌入 Live2D 模型，替代 QPainter 手绘。
# 支持自动眨眼、眼珠跟随鼠标、晃动随鼠标、摇尾巴、说话嘴型、表情切换。
# ============================================================

from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
import os


WIDGET_WIDTH = 200
WIDGET_HEIGHT = 280


class _ConsolePage(QWebEnginePage):
    """捕获 JS console，转发到 Python stdout 排查加载失败（PySide6 用重写而非信号）"""

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        # Windows 控制台默认 GBK，遇到 emoji 会 UnicodeEncodeError，先转安全再打印
        safe = str(message).encode("gbk", "replace").decode("gbk")
        print(f"[栗栗 JS] {safe}")


class Live2DPetWidget(QWidget):
    """
    Live2D 角色控件
    --------------
    用 QWebEngineView 加载本地 Live2D 模型（resources/live2d/ 下）。
    眨眼/摇尾巴在 HTML 里自己跑，鼠标跟随由这里轮询全局鼠标位置喂给 JS。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WIDGET_WIDTH, WIDGET_HEIGHT)

        # 透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # WebEngine 视图
        self._webview = QWebEngineView(self)
        self._webview.setFixedSize(WIDGET_WIDTH, WIDGET_HEIGHT)
        self._webview.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._webview.setStyleSheet("background: transparent;")
        # 换成自定义 Page：重写 javaScriptConsoleMessage，把 JS 报错透传到 Python stdout
        self._webview.setPage(_ConsolePage(self._webview))
        self._webview.page().setBackgroundColor(Qt.GlobalColor.transparent)

        # 允许 file:// 页面读本地模型文件（.model3.json / .moc3 / 贴图），否则 fetch 被拦
        settings = self._webview.page().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        # 加载 Live2D HTML
        html_path = os.path.join(
            os.path.dirname(__file__), "resources", "live2d", "tamias.html"
        )
        print(f"[栗栗] Live2D HTML: {html_path}")
        self._webview.page().loadFinished.connect(
            lambda ok: print(f"[栗栗] 页面加载{'成功' if ok else '失败'}"))
        self._webview.load(QUrl.fromLocalFile(os.path.abspath(html_path)))

        layout.addWidget(self._webview)

        # 就绪标记
        self._ready = False

        # 定时器：启动后等待 WebEngine 加载完成
        self._init_timer = QTimer(self)
        self._init_timer.timeout.connect(self._check_ready)
        self._init_timer.start(500)

        # 鼠标跟随：定时轮询全局鼠标位置（20fps）
        self._mouse_timer = QTimer(self)
        self._mouse_timer.timeout.connect(self._poll_mouse)
        self._mouse_timer.start(50)

    def _check_ready(self):
        """轮询检查 WebEngine 是否加载完成"""
        if self._ready:
            return
        self._webview.page().runJavaScript(
            "typeof model !== 'undefined' && model !== null",
            self._on_ready_check
        )

    def _on_ready_check(self, result):
        if result:
            self._ready = True
            self._init_timer.stop()
            print("[栗栗] Live2D 模型就绪")

    def _poll_mouse(self):
        """把全局鼠标位置归一化到 -1..1，驱动眼珠 + 晃动随鼠标。"""
        if not self._ready:
            return
        cursor = QCursor.pos()
        screen = QApplication.primaryScreen().availableGeometry()
        center = self.mapToGlobal(self.rect().center())
        nx = (cursor.x() - center.x()) / max(1, screen.width() / 2)
        ny = (cursor.y() - center.y()) / max(1, screen.height() / 2)
        nx = max(-1.0, min(1.0, nx))
        ny = max(-1.0, min(1.0, ny))
        self.track_mouse(nx, ny)

    def reload(self):
        """重新加载 Live2D 页面（内存看门狗调用：释放 QWebEngine 累积的内存）。
        重载后 _ready 置 False、就绪轮询重新开始，加载完自动恢复动画。"""
        self._ready = False
        html_path = os.path.join(
            os.path.dirname(__file__), "resources", "live2d", "tamias.html"
        )
        self._webview.load(QUrl.fromLocalFile(os.path.abspath(html_path)))
        self._init_timer.start(500)

    # ---------- 动画控制 ----------

    def on_clicked(self):
        """点击时触发惊喜表情"""
        if self._ready:
            self._webview.page().runJavaScript("onPoke();")

    def start_talking(self):
        """开始说话（嘴型动画）"""
        if self._ready:
            self._webview.page().runJavaScript("startTalking();")

    def stop_talking(self):
        """停止说话"""
        if self._ready:
            self._webview.page().runJavaScript("stopTalking();")

    def set_expression(self, expr: str):
        """切换表情：neutral, happy, surprise, sad 等"""
        if self._ready:
            self._webview.page().runJavaScript(f"setExpression('{expr}');")

    def track_mouse(self, x: float, y: float):
        """眼球跟随鼠标 + 晃动随鼠标"""
        if self._ready:
            self._webview.page().runJavaScript(f"trackMouse({x}, {y});")

    @property
    def is_ready(self) -> bool:
        return self._ready
