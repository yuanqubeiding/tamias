# ============================================================
# 栗栗（Tamias）— 精灵帧动画播放器
# ============================================================
# 播放「PNG 序列帧」动画（如打哈欠），盖在 Live2D 立绘上。
# 帧是 2x 分辨率（HiDPI 下清晰），显示时逻辑尺寸 = 像素尺寸 / 2。
# 预载 QPixmap + QTimer 逐帧切换，播完发 finished 信号。
# ============================================================

import glob
import json
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


class SpritePlayer(QLabel):
    """PNG 序列帧播放器。

    Args:
        anim_dir: 动画帧目录（内含 frame_*.png + 可选的 manifest.json）。
                  manifest.json 里可给 fps / logical_scale，缺省用 15 / 2。
        display_scale: 整体缩放倍数（1.0 = 原尺寸）。角色相对 Live2D 偏大/偏小时用它微调。
    """

    finished = Signal()

    def __init__(self, anim_dir: str, parent=None, display_scale: float = 1.0):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setScaledContents(False)

        # ---------- 读 manifest（fps / 逻辑缩放倍数） ----------
        self._fps = 15
        scale = 2
        manifest_path = os.path.join(anim_dir, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as fp:
                    m = json.load(fp)
                self._fps = int(m.get("fps", 15))
                scale = int(m.get("logical_scale", 2))
            except Exception:
                pass

        # ---------- 预载所有帧（按文件名排序 = 播放顺序） ----------
        self._frames: list[QPixmap] = []
        for path in sorted(glob.glob(os.path.join(anim_dir, "*.png"))):
            pm = QPixmap(path)
            if pm.isNull():
                continue
            # 整体缩放：display_scale 让角色相对 Live2D 略调大小（默认 1.0 原尺寸）
            if display_scale != 1.0:
                nw = max(1, round(pm.width() * display_scale))
                nh = max(1, round(pm.height() * display_scale))
                pm = pm.scaled(
                    nw, nh,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            pm.setDevicePixelRatio(scale)
            self._frames.append(pm)

        # 控件逻辑尺寸 = 第一帧的像素尺寸 / scale
        if self._frames:
            self.setFixedSize(
                self._frames[0].width() // scale,
                self._frames[0].height() // scale,
            )

        # ---------- 播放状态 ----------
        self._idx = 0
        self._loop = False        # 循环播放开关，play(loop=True) 时置 True
        self._loop_count = None   # 循环次数上限（None=无限循环，直到 stop）
        self._loops_done = 0      # 已完成的循环圈数
        self._ping_pong = False   # 正反往复循环（首末帧差异大时消除跳变，如说话口型）
        self._direction = 1       # 播放方向：1 正 / -1 反
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)

        self.hide()

    # ---------- 公共接口 ----------

    def play(self, loop: bool = False, loop_count: int | None = None, ping_pong: bool = False):
        """从头播放。
        loop=True 循环播；loop_count 给定时循环满该次数后停在当前帧并发 finished（不 hide，保持待机）。
        ping_pong=True 时正反往复循环（首末帧差异大时消除跳变，如说话口型一张一合）。
        没有帧时立即发 finished（让调用方正常恢复）。"""
        self._loop = loop
        self._loop_count = loop_count if loop else None
        self._loops_done = 0
        self._ping_pong = ping_pong and loop
        self._direction = 1
        if not self._frames:
            self.finished.emit()
            return
        self._idx = 0
        self.setPixmap(self._frames[0])
        self.show()
        self.raise_()
        interval = max(1, int(1000 / self._fps))
        self._timer.start(interval)

    def stop(self):
        """停止播放并隐藏。"""
        self._timer.stop()
        self.hide()

    @property
    def is_playing(self) -> bool:
        return self._timer.isActive()

    # ---------- 内部 ----------

    def _next_frame(self):
        self._idx += self._direction
        n = len(self._frames)
        # 正向到头（idx 越界到 n）
        if self._idx >= n:
            if not self._loop:
                self.stop()
                self.finished.emit()
                return
            if self._ping_pong:
                # 往返：从末帧回退一格反向继续（「一圈」在反向到头时计）
                self._direction = -1
                self._idx = n - 2
            else:
                # 正向循环：到头算一圈
                self._loops_done += 1
                if self._loop_count is not None and self._loops_done >= self._loop_count:
                    self._settle()
                    return
                self._idx = 0
            self.setPixmap(self._frames[self._idx])
            return
        # 反向到头（idx 越界到 -1）：完整往返一圈
        if self._idx < 0:
            self._loops_done += 1
            if self._loop_count is not None and self._loops_done >= self._loop_count:
                self._settle()
                return
            self._direction = 1
            self._idx = 1
            self.setPixmap(self._frames[self._idx])
            return
        self.setPixmap(self._frames[self._idx])

    def _settle(self):
        """循环够圈数：停 timer + hide + 发 finished（等同播完正常结束，调用方恢复立绘）。"""
        self.stop()
        self.finished.emit()
