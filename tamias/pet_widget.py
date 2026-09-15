# ============================================================
# 栗栗（Tamias）— 角色绘制控件（降级占位）
# ============================================================
# Live2D 模型加载失败时的降级：在透明背景画一颗会轻微晃动的栗子。
# 不画人脸——代码手绘二次元脸必然粗糙；画栗子没有五官可丑，还贴「栗栗」这个名字。
# 栗子用 ui_icons.draw_chestnut 画（托盘图标 / 欢迎头像兜底共用同一个画法）。
# ============================================================

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter
from PySide6.QtCore import QTimer

from tamias.animations import AnimationController
from tamias.ui_icons import draw_chestnut


# ---------- 常量 ----------

WIDGET_WIDTH = 200
WIDGET_HEIGHT = 280


class PetWidget(QWidget):
    """Live2D 降级占位：画一颗随动画控制器呼吸/晃动的栗子（无五官，保持生命感）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WIDGET_WIDTH, WIDGET_HEIGHT)

        # 动画控制器（呼吸晃动 + 弹跳，让栗子有生命感）
        self.animator = AnimationController(self)

        # 重绘定时器（30 FPS）
        self._repaint_timer = QTimer(self)
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_timer.start(33)

        self.animator.start()

    # ---------- 公共接口 ----------

    def on_clicked(self):
        """点击角色时触发惊喜动画（栗子没有表情，仅保留接口对称）。"""
        self.animator.trigger_surprise()

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        """画一颗栗子，随动画控制器的晃动/弹跳偏移。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        offset_x = self.animator.sway_offset_x
        offset_y = self.animator.sway_offset_y + self.animator.bounce_offset
        painter.translate(offset_x, offset_y)

        cx = self.width() // 2
        cy = self.height() // 2 + 20
        draw_chestnut(painter, cx, cy, 78)

        painter.end()
