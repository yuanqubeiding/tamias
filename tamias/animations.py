# ============================================================
# 栗栗（Tamias）— 动画控制器
# ============================================================
# 管理角色的闲置动画：眨眼、身体晃动等。
# 通过 QTimer 驱动动画帧，提供实时动画参数给绘制层。
# ============================================================

import random
import math
from PySide6.QtCore import QTimer, QObject


class AnimationController(QObject):
    """
    动画控制器
    ---------
    管理所有角色动画的状态和参数。
    每一帧更新后，通过信号或回调通知绘制层重绘。

    动画列表：
    - 眨眼动画：每 3~5 秒随机触发，眼睛闭合→睁开（约 200ms 周期）
    - 闲置晃动：轻微水平+垂直正弦摆动，模拟呼吸/浮动感
    - 点击反馈：预留接口
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---------- 主定时器 (约 30 FPS) ----------
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # ---------- 帧计数 ----------
        self._frame = 0  # 总帧数（从启动开始）

        # ---------- 眨眼动画状态 ----------
        self._blink_timer = 0       # 眨眼计时器（帧）
        self._blink_interval = 0    # 下次眨眼间隔（帧）
        self._blink_duration = 6    # 眨眼持续帧数（约 200ms @ 30fps）
        self._is_blinking = False   # 是否正在眨眼
        self._eye_open_ratio = 1.0  # 眼睛张开比例（1.0=全开, 0.0=全闭）

        # ---------- 闲置晃动状态 ----------
        self._sway_amplitude_x = 3.0  # 水平晃动幅度（像素）
        self._sway_amplitude_y = 2.0  # 垂直晃动幅度（像素）
        self._sway_speed = 0.03       # 晃动速度
        self._sway_offset_x = 0.0     # 当前水平偏移
        self._sway_offset_y = 0.0     # 当前垂直偏移

        # ---------- 点击反馈状态 ----------
        self._surprise_timer = 0      # 惊喜表情剩余帧数
        self._bounce_offset_y = 0.0   # 弹跳偏移

        # ---------- 初始化眨眼间隔 ----------
        self._schedule_next_blink()

    def start(self):
        """启动动画定时器"""
        self._timer.start(33)  # 约 33ms = 30 FPS

    def stop(self):
        """停止动画定时器"""
        self._timer.stop()

    def trigger_surprise(self):
        """
        触发惊喜表情（点击反馈）。
        眼睛睁大 + 短暂弹跳。
        """
        self._surprise_timer = 15  # 约 0.5 秒
        self._bounce_offset_y = -15

    # ---------- 公共属性（绘制层读取） ----------

    @property
    def eye_open_ratio(self) -> float:
        """眼睛张开比例：1.0 = 全开, 0.0 = 全闭"""
        return self._eye_open_ratio

    @property
    def sway_offset_x(self) -> float:
        """当前水平晃动偏移量（像素）"""
        return self._sway_offset_x

    @property
    def sway_offset_y(self) -> float:
        """当前垂直晃动偏移量（像素）"""
        return self._sway_offset_y

    @property
    def is_surprised(self) -> bool:
        """是否处于惊喜表情状态"""
        return self._surprise_timer > 0

    @property
    def bounce_offset(self) -> float:
        """弹跳偏移量"""
        return self._bounce_offset_y

    # ---------- 内部：每帧更新 ----------

    def _tick(self):
        """每帧调用一次，更新所有动画状态"""
        self._frame += 1

        # 1. 更新眨眼
        self._update_blink()

        # 2. 更新闲置晃动
        self._update_sway()

        # 3. 更新点击反馈
        self._update_surprise()

    def _update_blink(self):
        """更新眨眼动画状态"""
        if self._is_blinking:
            # 正在眨眼
            self._blink_timer += 1
            progress = self._blink_timer / self._blink_duration  # 0.0 → 1.0

            if progress <= 0.5:
                # 前半段：眼睛闭合 (1.0 → 0.0)
                self._eye_open_ratio = 1.0 - (progress * 2)
            else:
                # 后半段：眼睛睁开 (0.0 → 1.0)
                self._eye_open_ratio = (progress - 0.5) * 2

            # 眨眼结束
            if self._blink_timer >= self._blink_duration:
                self._is_blinking = False
                self._eye_open_ratio = 1.0
                self._schedule_next_blink()

        else:
            # 等待下次眨眼
            self._blink_timer += 1
            if self._blink_timer >= self._blink_interval:
                self._start_blink()

    def _start_blink(self):
        """开始一次眨眼"""
        self._is_blinking = True
        self._blink_timer = 0

    def _schedule_next_blink(self):
        """安排下次眨眼时间（3~5 秒后）"""
        self._blink_timer = 0
        # 随机间隔：90~150 帧 @ 30fps = 3~5 秒
        self._blink_interval = random.randint(90, 150)

    def _update_sway(self):
        """更新闲置晃动（正弦摆动）"""
        self._sway_offset_x = math.sin(self._frame * self._sway_speed) * self._sway_amplitude_x
        self._sway_offset_y = math.cos(self._frame * self._sway_speed * 1.3) * self._sway_amplitude_y

    def _update_surprise(self):
        """更新点击反馈状态"""
        if self._surprise_timer > 0:
            self._surprise_timer -= 1
            # 弹跳逐渐回弹
            progress = self._surprise_timer / 15
            self._bounce_offset_y = -15 * progress * progress  # 平方衰减

            if self._surprise_timer <= 0:
                self._bounce_offset_y = 0.0
