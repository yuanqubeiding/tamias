# ============================================================
# 栗栗（Tamias）— 精神值进度条气泡
# ============================================================
# 鼠标悬停在栗栗身上 2.5 秒后，在头顶弹出精神值（SAN）进度条：
# 白天满格 100；半夜 2:00~6:00 随夜深线性下降。让主人一眼看到
# 「栗栗困了、该睡觉了」，也是「关机让栗栗休息」的拟人养成交互。
#
# 参考 bubble.py 的 BubbleWidget：独立透明置顶窗口，paintEvent 自绘，
# 不抢焦点、鼠标穿透，随皮套定位。
# ============================================================

from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen

from tamias.i18n import tr
from tamias.fonts import ui_font


class SpiritMeter(QWidget):
    """精神值进度条：米白底圆角气泡，内含「栗栗精神值 xx/100」+ 一条进度条。

    进度条填充色随精神值变化：≤30 偏红（困得难受），其余暖橙（精神尚可）。
    """

    BG = QColor("#FFF9F0")        # 米白底（同对话气泡）
    BORDER = QColor("#C7A27E")    # 暖棕描边
    TEXT = QColor("#463329")      # 深棕文字
    BAR_BG = QColor("#EDE0CF")    # 进度条背景（浅暖灰）
    BAR_FILL = QColor("#E8A85C")  # 进度条填充（暖橙，精神尚可）
    BAR_LOW = QColor("#D97B6B")   # 精神值低时的填充（偏红，困得难受）
    W = 156                       # 气泡宽
    H = 54                        # 气泡高

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._san = 100
        self.setFixedSize(self.W, self.H)
        self.hide()

    def show_value(self, san: int, pet_rect):
        """在皮套（pet_rect = 其 frameGeometry）头顶上方显示精神值。"""
        self._san = max(0, min(100, san))
        self._position_at(pet_rect)
        self.show()
        self.raise_()
        self.update()

    def _position_at(self, pet_rect):
        """放到皮套头顶上方、整体偏左（跟对话气泡一个方位习惯）。"""
        head_x = pet_rect.x() + pet_rect.width() / 2
        pet_top = pet_rect.y()
        x = head_x - self.W / 2 - 30
        y = pet_top - self.H - 10
        x = max(int(x), 4)
        y = max(int(y), 4)
        self.move(int(x), int(y))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 1. 背景圆角气泡
        painter.setBrush(self.BG)
        painter.setPen(QPen(self.BORDER, 1.5))
        painter.drawRoundedRect(0, 0, self.W, self.H, 12, 12)

        # 2. 文字：栗栗精神值 xx / 100
        painter.setPen(self.TEXT)
        painter.setFont(ui_font(10))
        text = tr("栗栗精神值") + f" {self._san} / 100"
        painter.drawText(
            QRectF(10, 6, self.W - 20, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

        # 3. 进度条：背景槽 + 按精神值比例填充
        bar_x, bar_y, bar_w, bar_h = 10, 32, self.W - 20, 10
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.BAR_BG)
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 5, 5)
        fill_w = int(bar_w * self._san / 100)
        if fill_w > 0:
            fill = self.BAR_LOW if self._san <= 30 else self.BAR_FILL
            painter.setBrush(fill)
            painter.drawRoundedRect(bar_x, bar_y, fill_w, bar_h, 5, 5)
