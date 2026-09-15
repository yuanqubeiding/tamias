# ============================================================
# 栗栗（Tamias）— 功能库对话框
# ============================================================
# 栗栗的「工具箱」——一些好用的小功能，随点随用。
# 目前有：查天气、随机决定、番茄钟（后续再往这里加：便签、单位换算、
# 定时提醒等）。一行一个功能卡片，各卡片独立、互不干扰。
#
# 约定：所有卡片统一用 _card() 造「标题 + 圆角边框」的外壳，内部
# 控件加到返回的内布局里；要跑后台/耗时的才开线程（比如天气拉网），
# 纯本地的（随机、倒计时）直接在主线程做。
# ============================================================

import random
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QFrame, QWidget, QApplication, QComboBox,
)

from tamias.i18n import tr
from tamias.fonts import ui_font
from tamias.ui_icons import apply_icon, icon, strip_leading_emoji
from tamias.theme import WARM as _C


# 随机决定「吃什么」的候选池（本地列表，随点随取，零 API）
_FOODS = [
    "火锅", "麻辣烫", "米线", "饺子", "寿司", "汉堡",
    "盖浇饭", "炒饭", "烧烤", "粥", "轻食沙拉", "螺蛳粉",
]

# 番茄钟两个阶段的时长（秒）
_FOCUS_SECONDS = 25 * 60   # 专注 25 分钟
_BREAK_SECONDS = 5 * 60    # 休息 5 分钟

# 单位换算表：(下拉选项文案, 换算函数)。本地查表换算，零 API、零 key。
_CONVERSIONS = [
    ("摄氏 °C → 华氏 °F", lambda c: c * 9 / 5 + 32),
    ("华氏 °F → 摄氏 °C", lambda f: (f - 32) * 5 / 9),
    ("厘米 cm → 英寸 in", lambda x: x / 2.54),
    ("英寸 in → 厘米 cm", lambda x: x * 2.54),
    ("米 m → 英尺 ft", lambda x: x * 3.28084),
    ("公里 km → 英里 mi", lambda x: x * 0.621371),
    ("公斤 kg → 磅 lb", lambda x: x * 2.20462),
    ("GB → MB", lambda x: x * 1024),
    ("MB → GB", lambda x: x / 1024),
]


class FeatureLibrary(QDialog):
    """栗栗功能库。列出可用小功能，点按钮即用。"""

    # 天气拉取完成信号（后台线程 emit → 主线程更新标签，跨线程安全）
    _weather_done = Signal(str)

    def __init__(self, settings=None, parent=None, reminder=None):
        super().__init__(parent)
        self._settings = settings

        # —— 番茄钟状态（先初始化，_build_ui 里建卡片时会用到）——
        self._pomo_remaining = _FOCUS_SECONDS   # 剩余秒数
        self._pomo_phase = "focus"              # focus=专注 / break=休息
        self._pomo_running = False
        self._pomo_timer = QTimer(self)
        self._pomo_timer.timeout.connect(self._pomo_tick)

        # —— 定时提醒（应用层共享的单槽调度器；到点气泡+托盘，跟功能库窗口关不关无关）——
        self._reminder = reminder
        self._reminder_tick = QTimer(self)
        self._reminder_tick.setInterval(1000)
        self._reminder_tick.timeout.connect(self._refresh_reminder_status)

        self.setWindowTitle(tr("栗栗 - 功能库"))
        self.setMinimumSize(440, 360)
        self.setModal(True)
        # 暖棕侦探风背景，跟设置/资源库对话框统一
        self.setStyleSheet(f"QDialog {{ background: {_C['bg']}; }}")

        self._build_ui()

        # 天气结果从后台线程回来 → 主线程更新
        self._weather_done.connect(self._set_weather)

    # ---------- 界面搭建 ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # 标题（图标 + 文字）
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_ic = QLabel()
        title_ic.setPixmap(icon("layout-grid", 18).pixmap(18, 18))
        title_row.addWidget(title_ic)
        title = QLabel(strip_leading_emoji(tr("🧰 功能库")))
        title.setFont(ui_font(14, bold=True))
        title.setStyleSheet(f"color: {_C['title']};")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 说明
        desc = QLabel(tr("这里是栗栗的「工具箱」——一些好用的小功能，随点随用。"))
        desc.setWordWrap(True)
        desc.setFont(ui_font(10))
        desc.setStyleSheet(f"color: {_C['text']};")
        layout.addWidget(desc)

        # —— 卡片区（可滚动，功能多了也不会撑爆窗口）——
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            f"QScrollBar::handle:vertical {{ background: {_C['border']}; border-radius: 4px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        cards = QWidget()
        cards.setStyleSheet("QWidget { background: transparent; }")
        cards_layout = QVBoxLayout(cards)
        cards_layout.setContentsMargins(0, 0, 4, 0)
        cards_layout.setSpacing(12)

        # 一行一张功能卡，往后加功能就再加一行 _add_xxx_card(cards_layout)
        self._add_weather_card(cards_layout)
        self._add_random_card(cards_layout)
        self._add_pomodoro_card(cards_layout)
        self._add_unit_card(cards_layout)
        self._add_reminder_card(cards_layout)

        cards_layout.addStretch()
        scroll.setWidget(cards)
        layout.addWidget(scroll, stretch=1)

        # 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton(tr("关闭"))
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(self._primary_btn_style())
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _card(self, title_text: str, icon_name: str | None = None):
        """造一张带标题的功能卡（圆角边框 + 内布局），返回 (卡片 widget, 内布局)。
        标题可选带 Lucide 图标（icon_name 传图标名，emoji 前缀自动剥掉）。"""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {_C['card']}; border: 1px solid {_C['divider']}; border-radius: 10px; }}"
        )
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        if icon_name:
            ic_lb = QLabel()
            ic_lb.setPixmap(icon(icon_name, 16).pixmap(16, 16))
            title_row.addWidget(ic_lb, 0, Qt.AlignmentFlag.AlignVCenter)
        t = QLabel(strip_leading_emoji(title_text))
        t.setFont(ui_font(12, bold=True))
        t.setStyleSheet(f"color: {_C['title']};")
        title_row.addWidget(t)
        title_row.addStretch()
        box.addLayout(title_row)
        return frame, box

    # ---------- 功能卡：查天气 ----------

    def _add_weather_card(self, parent):
        frame, box = self._card(tr("🌦️ 查天气"), "cloud-sun")

        # 城市输入行
        city_row = QHBoxLayout()
        city_row.setSpacing(10)
        city_lb = QLabel(tr("城市"))
        city_lb.setFont(ui_font(11))
        city_lb.setStyleSheet(f"color: {_C['title']};")
        city_row.addWidget(city_lb)
        self._city_edit = QLineEdit()
        self._city_edit.setPlaceholderText(tr("留空 = 按 IP 自动定位"))
        self._city_edit.setFont(ui_font(11))
        self._city_edit.setStyleSheet(
            f"QLineEdit {{ background: {_C['bg']}; color: {_C['text']}; border: 1px solid {_C['border']};"
            f" border-radius: 6px; padding: 5px 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C['primary']}; }}"
        )
        # 预填上次填过的城市（存在 config 里）
        if self._settings is not None:
            saved = self._settings.weather_city
            if saved:
                self._city_edit.setText(saved)
        city_row.addWidget(self._city_edit, 1)
        box.addLayout(city_row)

        # 按钮 + 结果行
        weather_row = QHBoxLayout()
        weather_row.setSpacing(10)
        self._weather_btn = QPushButton(tr("查一下"))
        self._weather_btn.setFixedWidth(90)
        self._weather_btn.setStyleSheet(self._primary_btn_style())
        self._weather_btn.clicked.connect(self._on_check_weather)
        weather_row.addWidget(self._weather_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._weather_label = QLabel(tr("点一下，看看你这里的天气~"))
        self._weather_label.setWordWrap(True)
        self._weather_label.setFont(ui_font(11))
        self._weather_label.setStyleSheet(f"color: {_C['title']};")
        weather_row.addWidget(self._weather_label, 1)
        box.addLayout(weather_row)

        parent.addWidget(frame)

    # ---------- 功能卡：随机决定 ----------

    def _add_random_card(self, parent):
        frame, box = self._card(tr("🎲 随机决定"), "dice-5")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for text, icon_name, handler in (
            (tr("🍜 吃什么"), "utensils", self._rand_food),
            (tr("🎲 掷骰子"), "dice-5", self._rand_dice),
            (tr("⚖️ 是/否"), "scale", self._rand_yesno),
        ):
            b = QPushButton()
            apply_icon(b, icon_name, text)
            b.setStyleSheet(self._mini_btn_style())
            b.clicked.connect(handler)
            btn_row.addWidget(b)
        btn_row.addStretch()
        box.addLayout(btn_row)

        self._rand_label = QLabel(tr("纠结的时候，让栗栗帮你选~"))
        self._rand_label.setWordWrap(True)
        self._rand_label.setFont(ui_font(11))
        self._rand_label.setStyleSheet(f"color: {_C['text']};")
        box.addWidget(self._rand_label)

        parent.addWidget(frame)

    # ---------- 功能卡：番茄钟 ----------

    def _add_pomodoro_card(self, parent):
        frame, box = self._card(tr("🍅 番茄钟"), "timer")

        self._pomo_label = QLabel("25:00")
        self._pomo_label.setFont(ui_font(26, bold=True))
        self._pomo_label.setStyleSheet(f"color: {_C['primary']};")
        self._pomo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._pomo_label)

        self._pomo_phase_label = QLabel(tr("专注 25 分钟 · 休息 5 分钟"))
        self._pomo_phase_label.setFont(ui_font(10))
        self._pomo_phase_label.setStyleSheet("color: #A98B6D;")
        self._pomo_phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._pomo_phase_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._pomo_start_btn = QPushButton()
        self._pomo_pause_btn = QPushButton()
        self._pomo_reset_btn = QPushButton()
        apply_icon(self._pomo_start_btn, "play", tr("▶ 开始"))
        apply_icon(self._pomo_pause_btn, "pause", tr("⏸ 暂停"))
        apply_icon(self._pomo_reset_btn, "rotate-ccw", tr("↺ 重置"))
        for b in (self._pomo_start_btn, self._pomo_pause_btn, self._pomo_reset_btn):
            b.setStyleSheet(self._mini_btn_style())
        self._pomo_start_btn.clicked.connect(self._pomo_start)
        self._pomo_pause_btn.clicked.connect(self._pomo_pause)
        self._pomo_reset_btn.clicked.connect(self._pomo_reset)
        # 初始未运行：暂停按钮置灰
        self._pomo_pause_btn.setEnabled(False)
        btn_row.addWidget(self._pomo_start_btn)
        btn_row.addWidget(self._pomo_pause_btn)
        btn_row.addWidget(self._pomo_reset_btn)
        btn_row.addStretch()
        box.addLayout(btn_row)

        parent.addWidget(frame)

    # ---------- 功能卡：单位换算 ----------

    def _add_unit_card(self, parent):
        frame, box = self._card(tr("🧮 单位换算"), "calculator")

        # 换算类型下拉
        self._conv_combo = QComboBox()
        for label, _ in _CONVERSIONS:
            self._conv_combo.addItem(label)
        self._conv_combo.setFont(ui_font(11))
        self._conv_combo.setStyleSheet(
            f"QComboBox {{ background: {_C['bg']}; color: {_C['text']}; border: 1px solid {_C['border']};"
            f" border-radius: 6px; padding: 5px 8px; }}"
            f"QComboBox::drop-down {{ border: none; width: 20px; }}"
            f"QComboBox QAbstractItemView {{ background: {_C['card']}; color: {_C['text']};"
            f" selection-background-color: {_C['card_soft']}; }}"
        )
        box.addWidget(self._conv_combo)

        # 输入 + 结果行（输入变化即实时换算）
        conv_row = QHBoxLayout()
        conv_row.setSpacing(10)
        self._conv_edit = QLineEdit()
        self._conv_edit.setPlaceholderText(tr("输入数字"))
        self._conv_edit.setFont(ui_font(11))
        self._conv_edit.setStyleSheet(
            f"QLineEdit {{ background: {_C['bg']}; color: {_C['text']}; border: 1px solid {_C['border']};"
            f" border-radius: 6px; padding: 5px 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C['primary']}; }}"
        )
        conv_row.addWidget(self._conv_edit, 1)
        self._conv_label = QLabel(tr("输入数字，自动换算"))
        self._conv_label.setWordWrap(True)
        self._conv_label.setFont(ui_font(11))
        self._conv_label.setStyleSheet(f"color: {_C['title']};")
        conv_row.addWidget(self._conv_label, 1)
        box.addLayout(conv_row)

        # 换类型 / 改输入都触发重算
        self._conv_combo.currentIndexChanged.connect(self._convert)
        self._conv_edit.textChanged.connect(self._convert)

        parent.addWidget(frame)

    # ---------- 功能卡：定时提醒 ----------

    def _add_reminder_card(self, parent):
        frame, box = self._card(tr("⏰ 定时提醒"), "bell")

        # 内容输入（留空 = 默认「时间到啦～」）
        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        content_lb = QLabel(tr("内容"))
        content_lb.setFont(ui_font(11))
        content_lb.setStyleSheet(f"color: {_C['title']};")
        content_row.addWidget(content_lb)
        self._reminder_edit = QLineEdit()
        self._reminder_edit.setPlaceholderText(tr("提醒我做什么（留空 = 时间到）"))
        self._reminder_edit.setFont(ui_font(11))
        self._reminder_edit.setStyleSheet(
            f"QLineEdit {{ background: {_C['bg']}; color: {_C['text']}; border: 1px solid {_C['border']};"
            f" border-radius: 6px; padding: 5px 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C['primary']}; }}"
        )
        content_row.addWidget(self._reminder_edit, 1)
        box.addLayout(content_row)

        # 分钟：快捷按钮 + 自定义输入
        min_row = QHBoxLayout()
        min_row.setSpacing(6)
        min_lb = QLabel(tr("分钟"))
        min_lb.setFont(ui_font(11))
        min_lb.setStyleSheet(f"color: {_C['title']};")
        min_row.addWidget(min_lb)
        self._reminder_min_edit = QLineEdit("10")
        self._reminder_min_edit.setFixedWidth(48)
        self._reminder_min_edit.setFont(ui_font(11))
        self._reminder_min_edit.setStyleSheet(
            f"QLineEdit {{ background: {_C['bg']}; color: {_C['text']}; border: 1px solid {_C['border']};"
            f" border-radius: 6px; padding: 5px 8px; }}"
            f"QLineEdit:focus {{ border: 1px solid {_C['primary']}; }}"
        )
        min_row.addWidget(self._reminder_min_edit)
        for m in (5, 10, 30, 60):
            b = QPushButton(str(m))
            b.setStyleSheet(self._mini_btn_style())
            b.clicked.connect(lambda checked=False, mm=m: self._reminder_min_edit.setText(str(mm)))
            min_row.addWidget(b)
        min_row.addStretch()
        box.addLayout(min_row)

        # 开始/取消 + 状态
        act_row = QHBoxLayout()
        act_row.setSpacing(10)
        self._reminder_btn = QPushButton()
        apply_icon(self._reminder_btn, "play", tr("▶ 开始提醒"))
        self._reminder_btn.setStyleSheet(self._primary_btn_style())
        self._reminder_btn.clicked.connect(self._on_reminder_toggle)
        act_row.addWidget(self._reminder_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._reminder_status = QLabel(tr("设个提醒，到点栗栗会提醒你～"))
        self._reminder_status.setWordWrap(True)
        self._reminder_status.setFont(ui_font(11))
        self._reminder_status.setStyleSheet(f"color: {_C['title']};")
        act_row.addWidget(self._reminder_status, 1)
        box.addLayout(act_row)

        # 到点 → 状态标「已提醒」（信号来自应用层调度器，功能库窗口关不关都响）
        if self._reminder is not None:
            self._reminder.remind.connect(self._on_reminder_fired)

        parent.addWidget(frame)

    # ---------- 天气逻辑 ----------

    def _on_check_weather(self):
        """点「查一下」→ 读城市输入（留空=自动），后台线程拉天气，避免阻塞界面。"""
        city = self._city_edit.text().strip()
        # 记住用户填的城市到 config（留空 = 清掉手动城市、退回自动定位）
        if self._settings is not None:
            try:
                self._settings.weather_city = city
            except Exception:
                pass  # 存不上也不影响查天气
        self._weather_btn.setEnabled(False)
        self._weather_label.setText(tr("正在查天气…"))

        def _run():
            from tamias.weather import fetch_weather
            result = fetch_weather(city) or tr("查天气失败，请检查网络后重试。")
            try:
                self._weather_done.emit(result)
            except RuntimeError:
                pass  # 对话框已关、对象已销毁，不更新也无妨

        threading.Thread(target=_run, daemon=True).start()

    def _set_weather(self, text):
        """回主线程更新结果标签，并恢复按钮。"""
        try:
            self._weather_btn.setEnabled(True)
            self._weather_label.setText(text)
        except RuntimeError:
            pass

    # ---------- 随机决定逻辑 ----------

    def _rand_food(self):
        self._rand_label.setText(tr("今天就吃：{}", random.choice(_FOODS)))

    def _rand_dice(self):
        self._rand_label.setText(tr("掷出：🎲 {} 点", random.randint(1, 6)))

    def _rand_yesno(self):
        self._rand_label.setText(tr("栗栗的答案：{}", random.choice(("是", "否"))))

    # ---------- 番茄钟逻辑 ----------

    def _pomo_start(self):
        self._pomo_running = True
        self._pomo_timer.start(1000)
        self._pomo_start_btn.setEnabled(False)
        self._pomo_pause_btn.setEnabled(True)

    def _pomo_pause(self):
        self._pomo_running = False
        self._pomo_timer.stop()
        self._pomo_start_btn.setEnabled(True)
        self._pomo_pause_btn.setEnabled(False)

    def _pomo_reset(self):
        """回到初始状态：专注 25 分钟，未运行。"""
        self._pomo_timer.stop()
        self._pomo_running = False
        self._pomo_phase = "focus"
        self._pomo_remaining = _FOCUS_SECONDS
        self._pomo_start_btn.setEnabled(True)
        self._pomo_pause_btn.setEnabled(False)
        self._pomo_label.setText("25:00")
        self._pomo_phase_label.setText(tr("专注 25 分钟 · 休息 5 分钟"))

    def _pomo_tick(self):
        """每秒走一格；倒计时归零就切换阶段（专注↔休息）并哔一声提示。"""
        self._pomo_remaining -= 1
        if self._pomo_remaining <= 0:
            if self._pomo_phase == "focus":
                self._pomo_phase = "break"
                self._pomo_remaining = _BREAK_SECONDS
                self._pomo_phase_label.setText(tr("专注结束，休息 5 分钟～"))
            else:
                self._pomo_phase = "focus"
                self._pomo_remaining = _FOCUS_SECONDS
                self._pomo_phase_label.setText(tr("休息结束，继续专注 25 分钟～"))
            QApplication.beep()  # 阶段切换提示音
        mm, ss = divmod(self._pomo_remaining, 60)
        self._pomo_label.setText(f"{mm:02d}:{ss:02d}")

    # ---------- 单位换算逻辑 ----------

    def _convert(self, *_):
        """输入数字或切换类型 → 实时换算并回填结果；空/非法输入给友好提示。"""
        text = self._conv_edit.text().strip()
        if not text:
            self._conv_label.setText(tr("输入数字，自动换算"))
            return
        try:
            val = float(text)
        except ValueError:
            self._conv_label.setText(tr("请输入数字（如 100）"))
            return
        func = _CONVERSIONS[self._conv_combo.currentIndex()][1]
        # :.6g 保留 6 位有效数字，自动去掉多余的尾 0
        self._conv_label.setText(f"{func(val):.6g}")

    # ---------- 定时提醒逻辑 ----------

    def _on_reminder_toggle(self):
        """开始/取消定时提醒（单槽：新设覆盖旧的）。"""
        if self._reminder is None:
            return
        if self._reminder.active():
            self._reminder.cancel()
            self._reminder_tick.stop()
            apply_icon(self._reminder_btn, "play", tr("▶ 开始提醒"))
            self._reminder_status.setText(tr("已取消提醒～"))
            return
        text = self._reminder_edit.text().strip() or tr("时间到啦～")
        try:
            minutes = float(self._reminder_min_edit.text().strip())
        except ValueError:
            minutes = 0.0
        if minutes <= 0:
            self._reminder_status.setText(tr("请输入有效的分钟数（如 10）"))
            return
        self._reminder.set(minutes, text)
        apply_icon(self._reminder_btn, "pause", tr("⏹ 取消提醒"))
        self._reminder_tick.start()
        self._refresh_reminder_status()

    def _refresh_reminder_status(self):
        """每秒刷一次倒计时；提醒不在进行中就停表。"""
        if self._reminder is None or not self._reminder.active():
            self._reminder_tick.stop()
            return
        sec = self._reminder.remaining()
        mm, ss = divmod(sec, 60)
        self._reminder_status.setText(tr("⏰ 还剩 {:02d}:{:02d}", mm, ss))

    def _on_reminder_fired(self, text):
        """到点：状态标「已提醒」，按钮恢复可再设。"""
        self._reminder_tick.stop()
        apply_icon(self._reminder_btn, "play", tr("▶ 开始提醒"))
        self._reminder_status.setText(tr("✅ 已提醒：{}", text or tr("时间到啦～")))

    # ---------- 样式 ----------

    @staticmethod
    def _primary_btn_style():
        return f"""
            QPushButton {{
                background-color: {_C['primary']};
                color: {_C['white']};
                border: none;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {_C['primary_hover']}; }}
            QPushButton:disabled {{ background-color: #C9B49F; }}
        """

    @staticmethod
    def _mini_btn_style():
        """卡片里的次级小按钮（随机决定、番茄钟的控制键）——浅棕底、描边、白字换成暖棕。"""
        return f"""
            QPushButton {{
                background-color: {_C['bg']};
                color: {_C['title']};
                border: 1px solid {_C['border']};
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {_C['card_soft']}; }}
            QPushButton:pressed {{ background-color: {_C['divider']}; }}
            QPushButton:disabled {{ color: #B89E85; border-color: #D9C6B0; }}
        """


# ============================================================
# 模块级测试（只验证对话框能打开）
# ============================================================
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    dlg = FeatureLibrary()
    print("功能库对话框已打开")
    dlg.exec()
