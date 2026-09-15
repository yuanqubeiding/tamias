# ============================================================
# 栗栗（Tamias）— 定时提醒调度器
# ============================================================
# 用户主动设的「一次性闹钟」：到点弹桌宠气泡 + 托盘通知 + 提示音。
# 跟陪伴调度器（companion.py 的久坐/喝水/深夜）不同——那个是自动的、
# 分钟级；这个是用户手设的、秒级倒计时，且是「单个提醒」（新设覆盖旧的，
# 像手机闹钟）。
#
# 生命周期跟栗栗进程绑一起：只要栗栗还开着（含收到托盘），到点就响；
# 只有「彻底退出」才不响（跟「关窗=托盘常驻、进程不退」同一生命线）。
# 不落盘、不跨重启——重启栗栗后提醒清空（MVP 够用，跟陪伴提醒一致）。
# ============================================================

from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal


class ReminderScheduler(QObject):
    """单槽定时提醒调度器：set() 设一个、cancel() 取消、remaining() 查剩余秒数，
    到点发 remind(内容) 信号。秒级 QTimer 只在有提醒时跑，空闲不空转。"""

    remind = Signal(str)  # 到点触发，带提醒内容

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""          # 提醒内容
        self._deadline = None    # 到点时刻（datetime）
        self._active = False

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ---------- 对外接口 ----------

    def set(self, minutes: float, text: str) -> None:
        """设一个提醒（单槽：新设覆盖旧的）。minutes 为分钟数（可小数）。"""
        self._text = text or ""
        self._deadline = datetime.now() + timedelta(minutes=minutes)
        self._active = True
        self._timer.start()

    def cancel(self) -> None:
        """取消当前提醒。"""
        self._active = False
        self._deadline = None
        self._text = ""
        self._timer.stop()

    def active(self) -> bool:
        return self._active

    def active_text(self) -> str:
        return self._text

    def remaining(self) -> int:
        """剩余秒数（未激活返回 0）。"""
        if not self._active or self._deadline is None:
            return 0
        return max(0, int((self._deadline - datetime.now()).total_seconds()))

    # ---------- 内部 ----------

    def _tick(self):
        if not self._active:
            self._timer.stop()
            return
        if self.remaining() <= 0:
            text = self._text
            self._active = False
            self._deadline = None
            self._text = ""
            self._timer.stop()
            self.remind.emit(text)
