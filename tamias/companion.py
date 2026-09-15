# ============================================================
# 栗栗（Tamias）— 陪伴调度器
# ============================================================
# 让栗栗「会主动关心主人」：定时弹气泡提醒（久坐 / 喝水 / 深夜）+ 闲时
# 主动搭话。全部本地话术库（零 token，不调 DeepSeek），跟 bubble.py 的
# GREETINGS / POKED 一个套路——中文原文当 i18n key，四语言自动跟。
#
# 调度：一个分钟级定时器，到点发 say(text) 信号，由 PetWindow 接住弹气泡。
# 频率克制（久坐 45 分钟、喝水 60 分钟、深夜一天一次、闲谈随机 30~90 分钟），
# 目标是贴心的管家，不是话痨，不能刷屏式打扰。
# ============================================================

import random
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from tamias.i18n import tr


# ---------- 话术库（中文原文 = i18n key） ----------

SIT_REMINDERS = [
    "坐了好久啦，起来伸个懒腰吧～",
    "栗栗提醒你：该起来活动活动啦！",
    "一直盯着屏幕可不好，起来走走？",
    "（扶了扶猎鹿帽）主人，起来活动一下肩颈吧～",
]

WATER_REMINDERS = [
    "喝口水吧，侦探也要补水哦～",
    "记得喝水！栗栗盯着你呢～",
    "工作再忙，水也别忘啦～",
    "来，歇口气，喝杯水～",
]

NIGHT_REMINDERS = [
    "都这么晚啦，早点休息呀～",
    "深夜啦，栗栗陪你收工去睡觉～",
    "熬夜伤身，快睡吧，明天栗栗还在～",
]

IDLE_CHATS = [
    "栗栗在呢，有需要随时喊～",
    "（整理了下风衣）今天也精神满满！",
    "嗯……栗栗在想，待会吃什么好呢～",
    "听说专注的人最帅啦，你也是～",
    "有案子要交给栗栗吗？没有的话栗栗就守着～",
]


# ---------- 提醒间隔（分钟） ----------

SIT_INTERVAL_MIN = 45          # 久坐提醒间隔
WATER_INTERVAL_MIN = 60        # 喝水提醒间隔
IDLE_INTERVAL_RANGE = (30, 90) # 闲时搭话随机间隔（分钟）


class Companion(QObject):
    """陪伴调度器：分钟级定时器，到点发 say(text) 信号。

    构造参数可缩短间隔，方便手动测试（生产用默认值即可）。
    """

    say = Signal(str)
    water = Signal(str)   # 喝水提醒专用：弹气泡 + 播递水（water）动画

    def __init__(self, parent=None, sit_min=SIT_INTERVAL_MIN,
                 water_min=WATER_INTERVAL_MIN, idle_min_range=IDLE_INTERVAL_RANGE,
                 tick_ms=60_000):
        super().__init__(parent)
        self._sit_min = sit_min
        self._water_min = water_min
        self._idle_min_range = idle_min_range

        self._last_sit = datetime.now()
        self._last_water = datetime.now()
        self._last_idle = datetime.now()
        self._idle_interval = random.randint(*idle_min_range)
        self._night_key = None  # 已弹过深夜提醒的「晚上」归属日

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(tick_ms)

    def _tick(self):
        now = datetime.now()
        hour = now.hour

        # 深夜（23:00 ~ 次日 07:00）：只弹一次深夜提醒，其余都安静
        if hour >= 23 or hour < 7:
            key = self._night_key_of(now)
            if self._night_key != key:
                self._night_key = key
                self.say.emit(tr(random.choice(NIGHT_REMINDERS)))
            return

        # 白天：久坐 → 喝水 → 闲时搭话（一次只弹一句，避免撞车）
        if (now - self._last_sit).total_seconds() >= self._sit_min * 60:
            self._last_sit = now
            self.say.emit(tr(random.choice(SIT_REMINDERS)))
            return
        if (now - self._last_water).total_seconds() >= self._water_min * 60:
            self._last_water = now
            self.water.emit(tr(random.choice(WATER_REMINDERS)))
            return
        if (now - self._last_idle).total_seconds() >= self._idle_interval * 60:
            self._last_idle = now
            self._idle_interval = random.randint(*self._idle_min_range)
            self.say.emit(tr(random.choice(IDLE_CHATS)))

    @staticmethod
    def _night_key_of(now: datetime):
        """把 0~7 点归到前一天，让 23:30 和 00:30 算同一个「晚上」，只弹一次。"""
        if now.hour < 7:
            return now.date() - timedelta(days=1)
        return now.date()
