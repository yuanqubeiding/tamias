# ============================================================
# 栗栗（Tamias）— 桌宠透明窗口
# ============================================================
# 使用 PySide6 创建一个透明、无边框、始终置顶的桌宠窗口。
# 支持拖拽移动、左键点击聊天、右键弹出设置菜单。
# ============================================================

import json
import os
import random
import sys
import time
from datetime import datetime

from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QApplication, QMenu, QLabel
from PySide6.QtCore import Qt, QPoint, QTimer, Signal, QPropertyAnimation
from PySide6.QtGui import QMouseEvent, QAction, QPixmap

from tamias.pet_widget import PetWidget, WIDGET_WIDTH, WIDGET_HEIGHT
from tamias.pet_widget_live2d import Live2DPetWidget
from tamias import app_paths
from tamias.i18n import tr
from tamias.fonts import ui_font
from tamias.ui_icons import apply_icon, strip_leading_emoji
from tamias.tray_icon import load_app_icon
from tamias.theme import WARM as _C


# ---------- 设置页左上角帽子彩蛋（连点 5 次弹「感谢测试」） ----------
# 隐藏的测试感谢彩蛋：用户在设置页左上角的小帽子图标上「限时连点 5 次」
# 触发感谢弹窗，感谢参与测试的朋友（不署名、不暴露任何 UID）。
EGG_HAT_PATH = os.path.join(os.path.dirname(__file__), "resources", "icon", "tamias_hat.png")
EGG_CLICK_WINDOW = 3.0          # 连点限时窗口（秒）：3 秒内点满才算真连击
EGG_CLICK_COUNT = 5             # 连点次数


# ---------- 打哈欠测试开关 ----------
# 设环境变量 TAMIAS_YAWN_TEST_SECONDS=<秒数>，打哈欠按固定秒数重复触发（真机看效果用）。
# 平时不设，走正常 3~5 分钟随机。
_YAWN_TEST_SECONDS = os.environ.get("TAMIAS_YAWN_TEST_SECONDS")


class _HatEasterEggLabel(QLabel):
    """设置页左上角的帽子小图标，限时连点 5 次触发彩蛋弹窗。

    可重复触发：设置对话框每次打开都是新建 dialog + 新建帽子，计数天然归零，
    下次打开又能再触发。"""

    easter_egg_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clicks = []  # 最近 EGG_CLICK_WINDOW 秒内的点击时间戳（monotonic 秒）

    def mousePressEvent(self, event):
        now = time.monotonic()
        # 只保留限时窗口内的点击，超时的自动作废
        self._clicks = [t for t in self._clicks if now - t <= EGG_CLICK_WINDOW]
        self._clicks.append(now)
        if len(self._clicks) >= EGG_CLICK_COUNT:
            self._clicks.clear()  # 触发后清空，允许再连点触发
            self.easter_egg_triggered.emit()
        super().mousePressEvent(event)


class PetWindow(QMainWindow):
    """
    栗栗桌宠主窗口
    -----------
    透明、无边框、始终置顶。
    左键点击 → 弹出聊天对话框
    右键点击 → 弹出设置菜单
    拖拽 → 移动位置
    """

    # 信号
    work_mode_changed = Signal(bool)
    pro_mode_changed = Signal(bool)
    working_dir_changed = Signal(str)
    language_changed = Signal(str)
    task_started = Signal()  # 干活真正开始（main.py work_handler 发）→ 播「闭眼思考」动画
    approval_waiting = Signal()  # 审批开始（栗栗递出夹纸板等主人点）
    approval_done = Signal()     # 审批结束（收回、恢复）

    def __init__(self, on_chat_message=None, always_work=False, pro_mode=False,
                 conv_store=None, settings=None, get_gateway=None,
                 refresh_dsh=None, dsh_status=None, on_cancel_work=None):
        super().__init__()

        self._on_chat_message = on_chat_message
        self._always_work = always_work
        self._pro_mode = pro_mode
        self._conv_store = conv_store
        self._settings = settings
        self._get_gateway = get_gateway  # 取 dsh 网关的取值函数（引擎晚就绪，读当前最新，避免快照成 None）
        self._refresh_dsh = refresh_dsh  # 手动刷新 dsh 回调（后台线程跑，返回是否成功）
        self._dsh_status = dsh_status    # 查询 dsh 连接状态回调（'ok'/'down'）
        self._on_cancel_work = on_cancel_work  # 「终止」干活回调（后台线程跑，打断当前任务）

        # ---------- 窗口基本设置 ----------
        self.setWindowTitle(tr("栗栗"))
        self.setWindowIcon(load_app_icon())
        self.setFixedSize(WIDGET_WIDTH, WIDGET_HEIGHT)

        # ---------- 透明无边框设置 ----------
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )

        # ---------- 中央控件 ----------
        central = QWidget(self)
        central.setStyleSheet("background: transparent;")
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            self.pet_widget = Live2DPetWidget(self)
            print("[栗栗] 使用 Live2D 模型")
        except Exception as e:
            print(f"[栗栗] Live2D 不可用({e})，降级为 QPainter")
            self.pet_widget = PetWidget(self)
        layout.addWidget(self.pet_widget)

        # 透明覆盖层：浮在 pet_widget 上方捕获所有点击
        self._overlay = QWidget(central)
        self._overlay.setStyleSheet("background: transparent;")
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._overlay.setGeometry(0, 0, WIDGET_WIDTH, WIDGET_HEIGHT)
        self._overlay.installEventFilter(self)
        self._overlay.setAcceptDrops(True)  # 接受文件拖入（拖文件到栗栗身上开项目）
        self._overlay.setMouseTracking(True)  # 无按键也派发鼠标移动（悬停精神值用）
        self._overlay.raise_()  # 确保在最顶层

        # ---------- 拖拽相关 ----------
        self._drag_start_pos: QPoint | None = None
        self._drag_distance = 0

        # ---------- 长按捏脸（按住栗栗 1.5 秒触发左/右脸捏）----------
        self._press_pos = None            # 按下时的本地坐标（用于判左/右脸）
        self._long_press_fired = False    # 本次按住是否已触发捏脸（避免松手又触发一次 poke）
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(1500)   # 按住 1.5 秒
        self._long_press_timer.timeout.connect(self._on_long_press)

        # ---------- 连续左键点击 5 次 → 生气 ----------
        self._rapid_clicks = 0                   # 连续点击计数
        self._rapid_click_timer = QTimer(self)   # 间隔太久没点就归零（不算「连续」）
        self._rapid_click_timer.setSingleShot(True)
        self._rapid_click_timer.setInterval(1200)   # 1.2 秒内没下一击 → 计数清零
        self._rapid_click_timer.timeout.connect(self._reset_rapid_clicks)

        # ---------- 聊天对话框（复用）----------
        self._chat_dialog = None

        # ---------- 对话气泡（复用，启动问候 + 被戳反应）----------
        self._bubble = None

        # ---------- 右键菜单 ----------
        self._build_context_menu()

        # ---------- 定位（不在这里 show：显示交给 main.py 调 show_with_animation 播一次出场动画）----------
        self._position_at_bottom_right()
        self.hide()

        # 启动问候气泡：等窗口定位/显示稳定后再弹，避免启动瞬间黑框和定位抖动
        QTimer.singleShot(600, self._show_startup_bubble)

        # ---------- 陪伴调度器：久坐 / 喝水 / 深夜提醒 + 闲时主动搭话 ----------
        # 全部本地话术库、零 token；到点发 say 信号 → 主线程弹气泡。
        from tamias.companion import Companion
        self._companion = Companion(self)
        self._companion.say.connect(self._show_text)
        self._companion.water.connect(self._on_water_reminder)

        # ---------- 定时提醒调度器：用户手设的一次性闹钟（到点气泡 + 托盘通知） ----------
        from tamias.reminder import ReminderScheduler
        self.reminder = ReminderScheduler(self)
        self.reminder.remind.connect(self._on_reminder)

        # ---------- 精灵帧动画（打哈欠=空闲触发 / 被戳=点击触发；盖住 Live2D 播，播完恢复） ----------
        self._sprites = {}           # 懒加载的精灵播放器 {名字: SpritePlayer}，首次触发时才建（省启动时间/内存）
        self._playing_sprite = None  # 正在播的精灵（避免打哈欠/被戳/看书叠在一起）
        self._playing_anim = None    # 正在播的是哪个动画（播完只重置它自己的空闲计时）
        # ---------- 社区动作 mod 口子（丢动作包进 animations/ 即生效，不用改代码） ----------
        self._mod_replace = {}   # 点名替换内置动作：{内置动作名: 社区目录名}
        self._mod_status = {}    # 新增「状态文字 → 社区动作」：{状态文字: 社区目录名}
        self._mod_idle = []      # 新增空闲动作：[{anim, min_sec, max_sec, next_at}]
        self._mod_meta = {}      # 社区动作播放参数：{社区目录名: {loop, ping_pong, dx, dy}}
        self._scan_mod_actions()
        self.task_started.connect(self._on_task_started)  # 干活开始 → 闭眼思考动画
        self._approval_pending = False  # 是否正在等主人审批（递出后未决）
        self._executing = False         # 是否正在执行命令（bash/pwsh，播对讲机通话动画用）
        self.approval_waiting.connect(self._on_approval_waiting)
        self.approval_done.connect(self._on_approval_done)
        self._fade_anim = None       # 隐藏/退出时的窗口渐隐动画（持有引用防被回收）
        self._after_disappear = None # 告别动画播完、渐隐结束后的回调（隐藏=None，退出=quit）
        self._disappearing = False   # 正在告别流程中，防连点重复触发
        self._last_activity = time.monotonic()   # 打哈欠空闲计时（用户交互或打哈欠播完重置）
        self._yawn_interval = self._pick_yawn_interval()
        self._last_book = time.monotonic()        # 看书空闲计时（独立，不被打哈欠重置）
        self._book_interval = self._pick_book_interval()
        self._idle_timer = QTimer(self)
        # 正常 20 秒查一次；测试模式 5 秒查一次，让固定秒数尽量准点触发
        self._idle_timer.setInterval(5_000 if _YAWN_TEST_SECONDS else 20_000)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()

        # ---------- 精神值（SAN）系统 ----------
        # 白天满格 100；半夜 2:00~6:00 随夜深线性掉到 0（纯时间函数，关掉重开=睡醒恢复）。
        # 掉到阈值触发困倦动画+台词；鼠标悬停 2.5 秒在头顶弹精神值进度条。
        self._spirit_meter = None     # 精神值进度条气泡（懒加载）
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(2500)   # 悬停 2.5 秒显示
        self._hover_timer.timeout.connect(self._on_hover_timeout)
        self._last_sleepy_san = None  # 上次触发困倦的档位（避免同档反复触发）

    # ---------- 右键菜单 ----------

    def _build_context_menu(self):
        """构建右键弹出菜单"""
        self._context_menu = QMenu(self)
        self._context_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {_C['bg']};
                border: 1px solid {_C['border']};
                border-radius: 6px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 30px 8px 15px;
                border-radius: 4px;
                font-size: 13px;
                color: {_C['text']};
            }}
            QMenu::item:selected {{
                background-color: {_C['hover_bg']};
            }}
            QMenu::separator {{
                height: 1px;
                background: {_C['divider']};
                margin: 4px 10px;
            }}
        """)

        # --- 设置 ---
        settings_action = apply_icon(QAction(self), "settings", tr("⚙️ 设置"))
        settings_action.triggered.connect(self._on_settings)
        self._context_menu.addAction(settings_action)

        # --- 使用说明 ---
        usage_action = apply_icon(QAction(self), "book-open", tr("📖 使用说明"))
        usage_action.triggered.connect(self._on_usage)
        self._context_menu.addAction(usage_action)

        # --- 资源库 ---
        library_action = apply_icon(QAction(self), "palette", tr("🎨 资源库"))
        library_action.triggered.connect(self._on_open_resource_library)
        self._context_menu.addAction(library_action)

        # --- 功能库（查天气等小工具） ---
        feature_action = apply_icon(QAction(self), "layout-grid", tr("🧰 功能库"))
        feature_action.triggered.connect(self._on_open_feature_library)
        self._context_menu.addAction(feature_action)

        # --- 导出异常日志（出问题时一键打包发给作者） ---
        export_logs_action = apply_icon(QAction(self), "clipboard", tr("📋 导出异常日志"))
        export_logs_action.triggered.connect(self._on_export_logs)
        self._context_menu.addAction(export_logs_action)

        # --- 隐藏栗栗（从桌面隐去立绘，系统托盘可再显示） ---
        hide_action = apply_icon(QAction(self), "eye-off", tr("🙈 隐藏栗栗"))
        hide_action.triggered.connect(self._on_hide)
        self._context_menu.addAction(hide_action)

        self._context_menu.addSeparator()

        # --- 退出 ---
        exit_action = apply_icon(QAction(self), "log-out", tr("👋 退出栗栗"))
        exit_action.triggered.connect(self._on_exit)
        self._context_menu.addAction(exit_action)

    def _on_export_logs(self):
        """导出异常日志：打包 logs/ 成 zip 存桌面，弹窗提示发给作者。"""
        try:
            from tamias.log_exporter import export_logs, show_export_success
            zip_path = export_logs()
            show_export_success(self, zip_path)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("栗栗"), tr("导出异常日志失败：{}", str(e)))

    def _on_hide(self):
        """隐藏栗栗立绘：先播「鞠躬告别」动画，播完渐隐后真正 hide（托盘双击/右键可再显示）。"""
        self.hide_with_animation()

    def hide_with_animation(self):
        """隐藏栗栗（桌宠右键菜单 + 托盘共用入口）：播告别动画，渐隐后 hide。"""
        # 气泡是独立顶级窗口，不随皮套窗口一起 hide，得单独隐藏，否则会留在原地
        if self._bubble is not None:
            self._bubble.hide()
        self._play_disappear(on_done=None)

    def show_with_animation(self):
        """显示栗栗（隐藏后重新出现）：窗口先透明，播「出场」动画，同时渐显。"""
        if self._disappearing:
            return  # 还在告别流程中，暂不能显示
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        # 播出场动画（盖住 Live2D），播完 _on_sprite_finished 恢复立绘
        if self._playing_sprite is not None and self._playing_sprite.is_playing:
            self._playing_sprite.stop()
        sprite = self._get_sprite("appear")
        self._playing_sprite = sprite
        self._playing_anim = "appear"
        self.pet_widget.hide()
        sprite.play()
        self._overlay.raise_()
        # 同时窗口渐显（比 2s 出场动作快，前 0.5s 就亮出来）
        if self._fade_anim is not None:
            self._fade_anim.stop()   # 停掉可能还在跑的旧渐隐，避免两个透明度动画打架
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(500)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _play_disappear(self, on_done):
        """播「消失（鞠躬告别）」动画：盖住 Live2D 播告别动作，播完 _on_sprite_finished
        里接窗口渐隐，渐隐结束执行 on_done（隐藏时为 None，退出时为 quit）。"""
        if self._disappearing:
            return  # 已在告别流程中，忽略连点
        self._disappearing = True
        if self._playing_sprite is not None and self._playing_sprite.is_playing:
            self._playing_sprite.stop()
        sprite = self._get_sprite("disappear")
        self._playing_sprite = sprite
        self._playing_anim = "disappear"
        self._after_disappear = on_done
        self.pet_widget.hide()
        sprite.play()
        self._overlay.raise_()   # 透明覆盖层压回最上，告别动画期间点击仍走聊天

    def _fade_out_then(self, callback):
        """窗口整体渐隐到透明；结束后 hide 并复位透明度，再执行 callback（可空）。"""
        if self._fade_anim is not None:
            self._fade_anim.stop()   # 停掉可能还在跑的渐显，避免两个透明度动画打架
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(350)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(lambda: self._on_fade_out_done(callback))
        self._fade_anim.start()

    def _on_fade_out_done(self, callback):
        """渐隐结束：真正隐藏窗口、透明度复位到 1.0（下次 show 才可见），再执行回调。"""
        self.hide()
        self.setWindowOpacity(1.0)
        self._disappearing = False
        if callback is not None:
            callback()

    def _on_usage(self):
        """打开「使用说明」阅读对话框（右键菜单入口）。"""
        from tamias.usage_viewer import show_usage_guide
        show_usage_guide(parent=self)

    def reload_live2d(self):
        """刷新 Live2D 立绘（内存看门狗调用，释放 QWebEngine 累积内存）。
        QPainter 降级版（PetWidget）没有内存泄漏，这里空操作。"""
        if isinstance(self.pet_widget, Live2DPetWidget):
            self.pet_widget.reload()

    def _on_settings(self):
        """
        打开设置窗口，显示版本号和选项。
        """
        from tamias import __version__
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QPushButton, QSlider
        from PySide6.QtGui import QFont

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("栗栗 - 设置"))
        # 只固定宽度、不固定高度：繁体界面字号更大（13pt），高度交给布局自适应，避免文字挤在一起
        dialog.setFixedWidth(380)
        dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {_C['bg']};
                border: 2px solid {_C['border']};
                border-radius: 0px;
            }}
            QLabel {{
                color: {_C['text']};
            }}
            QCheckBox {{
                color: {_C['text']};
                font-size: 13px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                background: {_C['white']};
                border: 1px solid {_C['border']};
            }}
            QCheckBox::indicator:checked {{
                background: {_C['primary']};
                border-color: {_C['primary']};
            }}
            QComboBox {{
                background: {_C['white']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 120px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            /* 下拉弹层：显式白底深字 + 选中高亮。
               不加的话弹层是独立顶级窗口，不受上面 QComboBox 规则约束，
               Windows 深色主题下会白底白字「发白看不清选项」。 */
            QComboBox QAbstractItemView {{
                background: {_C['white']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                selection-background-color: {_C['hover_bg']};
                selection-color: {_C['text']};
                outline: 0;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 24px;
                padding: 4px 8px;
            }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # 标题
        title = QLabel(tr("栗栗 桌面智能助手"))
        title_font = ui_font(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_C['title']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 左上角帽子彩蛋：限时连点 5 次触发感谢弹窗（测试感谢彩蛋）。
        # 帽子小图标绝对定位在左上角（不占布局），标题仍居中；图标缺失则彩蛋静默失效。
        hat = _HatEasterEggLabel(dialog)
        hat_pixmap = QPixmap(EGG_HAT_PATH)
        if not hat_pixmap.isNull():
            hat.setPixmap(hat_pixmap)
            hat.move(10, 8)
            hat.easter_egg_triggered.connect(lambda: self._show_tester_egg(dialog))
            hat.show()

        # 版本号
        version_label = QLabel(tr("版本：v{}", __version__))
        version_label.setFont(ui_font(10))
        version_label.setStyleSheet(f"color: {_C['muted']};")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        # 作者署名（明水印：GitHub，可查证防冒名）+ 一键复制主页链接
        author_row = QHBoxLayout()
        author_row.addStretch()
        author_label = QLabel(tr("作者：GitHub {}", "github.com/yuanqubeiding"))
        author_label.setFont(ui_font(9))
        author_label.setStyleSheet(f"color: {_C['muted']};")
        # 允许鼠标选中复制（不然 UID 得一个字一个字抄）
        author_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        author_row.addWidget(author_label)
        copy_btn = apply_icon(QPushButton(), "clipboard", tr("📋 复制"))
        copy_btn.setFont(ui_font(9))
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_C['muted']};
                border: 1px solid {_C['border']};
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: {_C['hover_bg']}; }}
        """)
        copy_btn.clicked.connect(self._copy_author_link)
        author_row.addWidget(copy_btn)
        author_row.addStretch()
        layout.addLayout(author_row)

        # 第三方字体声明（鸿蒙协议要求「显著声明」，OFL 要求随附协议——详见 NOTICE.txt）
        font_notice = QLabel(tr("字体：HarmonyOS Sans SC · Noto Sans JP · JetBrains Mono（免费可商用）"))
        font_notice.setFont(ui_font(8))
        font_notice.setStyleSheet(f"color: {_C['primary']};")
        font_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_notice.setWordWrap(True)
        layout.addWidget(font_notice)

        # 界面框架声明（LGPL 允许闭源商用，Qt 官方建议在界面提一句；详见 NOTICE.txt）
        framework_notice = QLabel(tr("界面框架：Qt / PySide6（LGPLv3，开源许可见随包 NOTICE.txt）"))
        framework_notice.setFont(ui_font(8))
        framework_notice.setStyleSheet(f"color: {_C['primary']};")
        framework_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        framework_notice.setWordWrap(True)
        layout.addWidget(framework_notice)

        layout.addSpacing(5)

        # 始终干活开关
        work_check = apply_icon(QCheckBox(), "wrench", tr("🔧 始终干活模式"))
        work_check.setFont(ui_font(11))
        work_check.setChecked(self._always_work)
        work_check.toggled.connect(self._on_toggle_work_mode)
        layout.addWidget(work_check)

        # 专业模式开关
        pro_check = apply_icon(QCheckBox(), "zap", tr("⚡ 专业模式（显示计划+深色主题）"))
        pro_check.setFont(ui_font(11))
        pro_check.setChecked(self._pro_mode)
        pro_check.toggled.connect(self._on_toggle_pro_mode)
        layout.addWidget(pro_check)

        # 聊天气泡字号滑块：只调气泡正文（输入框不动）。拖动只改数字，松手才套用。
        cur_font = self._settings.chat_font_size if self._settings else 13
        font_row = QHBoxLayout()
        font_label = QLabel(strip_leading_emoji(tr("🔠 聊天气泡字号")))
        font_label.setFont(ui_font(11))
        font_row.addWidget(font_label)
        font_row.addStretch()
        font_val = QLabel(str(cur_font))
        font_val.setFont(ui_font(11))
        font_val.setMinimumWidth(24)
        font_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        font_row.addWidget(font_val)
        layout.addLayout(font_row)

        font_slider = QSlider(Qt.Orientation.Horizontal)
        font_slider.setRange(10, 20)
        font_slider.setSingleStep(1)
        font_slider.setPageStep(1)
        font_slider.setValue(cur_font)
        font_slider.valueChanged.connect(lambda v: font_val.setText(str(v)))
        font_slider.sliderReleased.connect(self._on_font_size_released)
        layout.addWidget(font_slider)

        # 开机自启动开关
        autostart_check = apply_icon(QCheckBox(), "rocket", tr("🚀 开机时自动启动栗栗"))
        autostart_check.setFont(ui_font(11))
        autostart_check.setChecked(self.auto_start)
        autostart_check.toggled.connect(self.set_auto_start)
        layout.addWidget(autostart_check)

        layout.addSpacing(4)

        # 语言选择
        lang_row = QHBoxLayout()
        lang_label = QLabel(strip_leading_emoji(tr("🌐 语言")))
        lang_label.setFont(ui_font(11))
        lang_row.addWidget(lang_label)
        lang_row.addStretch()
        lang_combo = QComboBox()
        # 语言名是各语言的自称，永远用本身显示，不 tr
        lang_combo.addItem("简体中文", "zh-CN")
        lang_combo.addItem("繁體中文", "zh-TW")
        lang_combo.addItem("English", "en")
        lang_combo.addItem("日本語", "ja")
        cur_lang = self._settings.language if self._settings else "zh-CN"
        idx = lang_combo.findData(cur_lang)
        lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(lang_combo)
        layout.addLayout(lang_row)

        # 切换提示
        lang_hint = QLabel(tr("切换语言后重启栗栗生效"))
        lang_hint.setFont(ui_font(9))
        lang_hint.setStyleSheet(f"color: {_C['muted']};")
        layout.addWidget(lang_hint)

        # API Key 入口（原来只挂在系统托盘菜单里，普通用户难发现 → 这里补一个入口）
        api_key_btn = apply_icon(QPushButton(), "key", tr("🔑 API Key"))
        api_key_btn.setFont(ui_font(11))
        api_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        api_key_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['white']};
                color: {_C['title']};
                border: 1px solid {_C['border']};
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background: {_C['hover_bg']}; }}
        """)
        api_key_btn.clicked.connect(lambda: self._open_api_key_dialog(dialog))
        layout.addWidget(api_key_btn)

        # 重启按钮
        restart_btn = apply_icon(QPushButton(), "refresh-cw", tr("🔄 重启栗栗"))
        restart_btn.setFont(ui_font(11))
        restart_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['primary']};
                color: {_C['white']};
                border: none;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {_C['primary_hover']}; }}
        """)
        restart_btn.clicked.connect(lambda: self._restart_app(dialog))
        layout.addWidget(restart_btn)

        # 使用说明入口（新手指引：看不懂栗栗能干嘛 → 点这里）
        from tamias.usage_viewer import show_usage_guide
        usage_btn = apply_icon(QPushButton(), "book-open", tr("📖 使用说明"))
        usage_btn.setFont(ui_font(11))
        usage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        usage_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['white']};
                color: {_C['title']};
                border: 1px solid {_C['border']};
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background: {_C['hover_bg']}; }}
        """)
        usage_btn.clicked.connect(lambda: show_usage_guide(parent=dialog))
        layout.addWidget(usage_btn)

        # 查看协议 / 隐私政策入口（合规要求：让用户能随时回看已同意的条款）
        from tamias.legal_viewer import show_legal_text
        legal_row = QHBoxLayout()
        for doc_name in ("用户协议", "隐私政策"):
            if doc_name == "用户协议":
                btn_text, icon_name = "📄 用户协议", "file-text"
            else:
                btn_text, icon_name = "🔒 隐私政策", "lock"
            legal_btn = apply_icon(QPushButton(), icon_name, tr(btn_text))
            legal_btn.setFont(ui_font(10))
            legal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            legal_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {_C['title']};
                    border: 1px solid {_C['border']};
                    border-radius: 8px;
                    padding: 7px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background: {_C['hover_bg']}; }}
            """)
            legal_btn.clicked.connect(lambda _=False, d=doc_name: show_legal_text(d, parent=dialog))
            legal_row.addWidget(legal_btn)
        layout.addLayout(legal_row)

        # 免责声明（法律撇清：工具中性原则——用户违法与作者无关）
        disclaimer = QLabel(tr("⚠️ 本软件仅供合法用途，请勿用于任何违法违规活动。由此产生的一切后果由使用者自行承担，与作者无关。"))
        disclaimer.setFont(ui_font(8))
        disclaimer.setStyleSheet(f"color: {_C['primary']};")
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)

        layout.addStretch()

        dialog.exec()

    def _show_tester_egg(self, parent=None):
        """设置页帽子连点彩蛋：感谢参与测试的朋友（不署名、不暴露任何 UID）。"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(parent, tr("🎩 隐藏彩蛋"), tr("感谢每一位参与测试的朋友"))

    def _open_api_key_dialog(self, parent=None):
        """打开 API Key 设置对话框（填/显/删）。
        复用 settings_dialog.SettingsDialog；gateway 用于双写闲聊(config.yaml) + 干活(dsh 凭据)两套 Key，
        gateway 为 None 时（引擎没开）自动降级为只写 config.yaml 并提示。"""
        from tamias.settings_dialog import SettingsDialog
        _gw = self._get_gateway() if self._get_gateway else None  # 读当前最新网关，别用启动时的 None 快照
        dlg = SettingsDialog(self._settings, gateway=_gw, parent=parent)
        dlg.exec()

    def _copy_author_link(self):
        """复制作者 GitHub 主页链接到剪贴板（设置窗口「📋 复制」按钮用）。"""
        QApplication.clipboard().setText("https://github.com/yuanqubeiding")
        btn = self.sender()
        if btn is not None:
            btn.setText(strip_leading_emoji(tr("✅ 已复制")))

            def _restore():
                try:
                    btn.setText(strip_leading_emoji(tr("📋 复制")))
                except RuntimeError:
                    pass  # 对话框已关、按钮已销毁，不恢复也无妨

            QTimer.singleShot(1500, _restore)

    def _on_open_resource_library(self):
        """打开资源库对话框（换人设/皮肤）。"""
        from tamias.resource_library import ResourceLibrary
        dlg = ResourceLibrary(self._settings, parent=self)
        dlg.exec()

    def _on_open_feature_library(self):
        """打开功能库对话框（查天气等小工具）。"""
        from tamias.feature_library import FeatureLibrary
        dlg = FeatureLibrary(self._settings, parent=self, reminder=self.reminder)
        dlg.exec()

    def _on_toggle_work_mode(self, checked: bool):
        """「始终干活」勾选框变化 → 走公共 set_work_mode。"""
        self.set_work_mode(checked)

    def set_work_mode(self, checked: bool):
        """切换「始终干活」模式（公共方法，桌宠菜单 + 托盘共用）。"""
        self._always_work = checked
        self.work_mode_changed.emit(checked)
        if checked:
            self.setToolTip(tr("栗栗 - 始终干活模式（所有消息直接干活）"))
        else:
            self.setToolTip(tr("栗栗 - 智能模式（自动判断闲聊/干活）"))

    def _on_toggle_pro_mode(self, checked: bool):
        """「专业模式」勾选框变化 → 走公共 set_pro_mode。"""
        self.set_pro_mode(checked)

    def set_pro_mode(self, checked: bool):
        """切换专业模式（公共方法，桌宠菜单 + 托盘共用）。"""
        self._pro_mode = checked
        # 打开专业模式 = 默认同时打开「始终干活」（用户嫌每次去设置开太麻烦）。
        # 只在「开启」时联动打开；反向不联动（关专业模式不动始终干活），
        # 已开则跳过避免重复 emit。想在专业模式里用智能路由，托盘再关一次即可。
        if checked and not self._always_work:
            self.set_work_mode(True)
        self.pro_mode_changed.emit(checked)
        if self._chat_dialog is not None:
            self._chat_dialog.set_pro_mode(checked)

    def _on_font_size_released(self):
        """字号滑块松手 → 套用（存配置 + 通知聊天框重建气泡）。"""
        slider = self.sender()
        size = int(slider.value()) if slider else 13
        if self._settings is not None:
            self._settings.chat_font_size = size
        if self._chat_dialog is not None:
            self._chat_dialog.set_chat_font_size(size)

    def _on_mode_switch_requested(self):
        """聊天框启动器上的「专业模式/普通模式」按钮被点 → 切到另一模式。
        走公共 set_pro_mode（会 emit pro_mode_changed 持久化到 settings + 回启动器）。"""
        self.set_pro_mode(not self._pro_mode)

    def set_auto_start(self, enabled: bool):
        """切换「开机自启动」（公共方法，桌宠设置 + 托盘共用）。
        直接写注册表 Run 键，注册表本身就是状态真相，不落 config.yaml。"""
        from tamias import auto_start
        auto_start.set_enabled(enabled)

    def _on_language_changed(self, index: int):
        """语言下拉框变化 → 取语言码，走公共 set_language。"""
        combo = self.sender()
        lang = combo.itemData(index) if combo else None
        self.set_language(lang)

    def set_language(self, lang):
        """切换界面语言（公共方法，桌宠菜单 + 托盘共用）：
        保存到配置 + 立即切 i18n + 通知 main 重设聊天回复语言。"""
        if not lang:
            return
        if self._settings:
            self._settings.language = lang
        from tamias.i18n import set_language
        set_language(lang)
        # 通知 main 重设聊天回复语言（人设 prompt 里的语言指令）
        self.language_changed.emit(lang)

    def _restart_app(self, dialog):
        """设置对话框里的「重启」按钮：先关对话框，再走公共 restart_app。"""
        dialog.close()
        self.restart_app()

    def restart_app(self):
        """重启栗栗（公共方法，桌宠设置 + 托盘共用）：
        释放单实例锁 → 拉起新进程 → 旧进程立即退出。
        打包后 sys.executable 是 tamias.exe，直接拉起；开发态用 python -m。"""
        import os, sys, subprocess
        from tamias.app_log import log, mask_path
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # 先正确释放单实例锁：必须用 QLockFile.unlock()（关闭句柄 + 删文件）；
        # os.remove 删不掉被独占打开的锁文件，会导致新进程误判「已经在运行」。
        # 记日志：重启失败的头号嫌疑就是「锁没释放干净 → 新进程被单实例检测拦住」，
        # 这里把释放结果 + 拉起结果都落盘，跟新进程的 [启动] 日志对照定位。
        try:
            from tamias.main import release_instance_lock
            release_instance_lock()
            log("[重启] 单实例锁已释放")
        except Exception as e:
            log(f"[重启] 释放单实例锁失败：{e}", "error")
        # 打包后 sys.executable 就是 tamias.exe，直接拉起；开发态才用 python -m
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, '-m', 'tamias.main']
        log(f"[重启] 准备拉起新进程 frozen={getattr(sys, 'frozen', False)} cmd={mask_path(' '.join(cmd))}")
        try:
            p = subprocess.Popen(
                cmd,
                cwd=project_dir,
                creationflags=0x08000000 if sys.platform == 'win32' else 0,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log(f"[重启] 新进程已拉起 PID={p.pid}，旧进程即将退出")
        except Exception as e:
            log(f"[重启] 拉起新进程失败：{e}", "error")
        os._exit(0)

    def _on_open_folder(self):
        """打开文件夹选择器，切换工作目录"""
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(
            self, tr("选择工作目录"), "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if folder:
            self.working_dir_changed.emit(folder)

    def _on_exit(self):
        """退出应用：先播「鞠躬告别」动画，渐隐后关窗退出。"""
        # 先关聊天对话框（别遮住告别动画）
        if self._chat_dialog is not None:
            self._chat_dialog.close()
            self._chat_dialog = None
        # 播告别动画 → 渐隐 → 关窗 + 退出
        self._play_disappear(on_done=self._quit_app)

    def _quit_app(self):
        """告别动画播完、渐隐结束：关窗退出应用。"""
        self.close()
        QApplication.instance().quit()

    # ---------- 窗口定位 ----------

    def _position_at_bottom_right(self):
        """定位到屏幕右下角"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        screen_geo = screen.availableGeometry()
        x = screen_geo.right() - WIDGET_WIDTH - 40
        y = screen_geo.bottom() - WIDGET_HEIGHT - 40
        self.move(x, y)

    # ---------- 鼠标事件 ----------

    def eventFilter(self, obj, event):
        """左右键拖拽移动窗口，左键短按聊天，右键短按菜单"""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            e = event
            self._reset_idle()  # 用户碰了皮套 → 重置打哈欠空闲计时
            self._drag_start_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_distance = 0
            # 左键按下 → 记位置 + 起长按计时（按手 1 秒摸手，其它 1.5 秒捏脸）
            if e.button() == Qt.MouseButton.LeftButton:
                self._press_pos = e.position().toPoint()
                self._long_press_fired = False
                self._long_press_timer.setInterval(1000 if self._is_on_hand(self._press_pos) else 1500)
                self._long_press_timer.start()
            return False
        elif event.type() == QEvent.Type.MouseMove:
            e = event
            if self._drag_start_pos is not None and e.buttons() & (
                Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
            ):
                self.move(e.globalPosition().toPoint() - self._drag_start_pos)
                self._drag_distance += 1
                # 拖动皮套时，让显示中的对话气泡跟着一起走
                if self._bubble is not None and self._bubble.isVisible():
                    self._bubble.move_with(self.frameGeometry())
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            e = event
            if e.button() == Qt.MouseButton.RightButton and self._drag_distance < 3:
                self._context_menu.popup(e.globalPosition().toPoint())
            elif e.button() == Qt.MouseButton.LeftButton and self._drag_distance < 5:
                self._long_press_timer.stop()
                # 1.5 秒内松手 = 普通点击（被戳）；已长按触发捏脸就不再当点击
                if not self._long_press_fired:
                    self._rapid_clicks += 1
                    self._rapid_click_timer.start()  # 每次点击重置计时窗
                    if self._rapid_clicks >= 5:
                        self._reset_rapid_clicks()
                        self._on_angry()
                    else:
                        self._on_clicked()
            self._drag_start_pos = None
            self._drag_distance = 0
            return False
        elif event.type() == QEvent.Type.Enter:
            # 鼠标悬停在栗栗身上 → 起 2.5 秒计时，到时弹精神值进度条
            self._hover_timer.start()
        elif event.type() == QEvent.Type.Leave:
            # 鼠标离开栗栗 → 停计时、收精神值气泡
            self._hover_timer.stop()
            self._hide_spirit_meter()
        elif event.type() == QEvent.Type.DragEnter:
            e = event
            # 只接受本地文件拖入（避免抢走拖文本 / 图片 URL 等无关拖拽）
            if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
                e.acceptProposedAction()
                return True
        elif event.type() == QEvent.Type.DragMove:
            e = event
            # 拖动过程中也必须持续接受，否则 Drop 不会派发（Qt 要求 enter+move 都 accept）
            if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
                e.acceptProposedAction()
                return True
        elif event.type() == QEvent.Type.Drop:
            e = event
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            e.acceptProposedAction()
            self._on_drop_files(paths)
            return True
        return super().eventFilter(obj, event)

    def contextMenuEvent(self, event):
        """
        右键点击：弹出设置菜单。
        """
        self._context_menu.popup(event.globalPos())
        event.accept()

    def _on_long_press(self):
        """左键按住栗栗触发：按在手部 → 摸手害羞（1 秒）；按脸 → 捏脸左/右（1.5 秒）；拖动中不算。"""
        if self._drag_distance >= 5:
            return  # 按住拖动了 = 在挪窗口，不是长按
        self._long_press_fired = True
        if self._is_on_hand(self._press_pos):
            # 按住手 → 害羞慌张动画 + 台词
            self._play_sprite_anim("hand_touch")
            self._show_bubble("hand_touch")
        elif self._press_pos is not None and self._press_pos.x() < WIDGET_WIDTH // 2:
            self._play_sprite_anim("pinch_left")
        else:
            self._play_sprite_anim("pinch_right")

    def _is_on_hand(self, pos) -> bool:
        """判断按下点是否落在栗栗的「手」附近（身体两侧、中部偏下）。"""
        if pos is None:
            return False
        x, y = pos.x(), pos.y()
        # 手垂在身体两侧：y 在中下部，x 靠左/右边缘（避开中间的脸和身体）
        if not (120 <= y <= 205):
            return False
        return x < 75 or x > WIDGET_WIDTH - 75

    def _is_on_head(self, pos) -> bool:
        """判断按下点是否落在栗栗的「头」上（身体正上方中部，手部区域以上）。"""
        if pos is None:
            return False
        x, y = pos.x(), pos.y()
        # 头在身体正上方：y 在手部（120 起）以上，x 居中（避开两侧的手）
        if y >= 120:
            return False
        return 75 <= x <= WIDGET_WIDTH - 75

    # ---------- 左键点击 → 聊天 ----------

    def _on_clicked(self):
        """左键点击：点头部 → 点头动画；点其他部位 → 被戳动画 + 气泡。都切聊天框显隐。"""
        if self._is_on_head(self._press_pos):
            # 点头部 = 点头（不弹「被戳」气泡）；其余行为照旧
            self._play_sprite_anim("nod")
        else:
            self._play_sprite_anim("poke")
            self._show_bubble("poked")

        self._ensure_chat_dialog()

        # 左键点击桌宠 = 聊天框显隐切换：显示中 → 收起（最小化）；隐藏/最小化 → 恢复。
        if self._chat_dialog.isVisible() and not self._chat_dialog.isMinimized():
            self._chat_dialog.showMinimized()
        else:
            # 用 restore_windows 统一还原：连可能开着的模态弹窗（干活回滚）一起拉回前台
            self._chat_dialog.restore_windows()

    def open_chat_dialog(self):
        """恢复/打开聊天（工作）界面——供托盘单击等外部入口调用（区别于左键「显隐切换」）。
        首次调用惰性创建聊天窗，然后统一 restore_windows 拉回前台（含可能开着的模态弹窗）。"""
        self._ensure_chat_dialog()
        self._chat_dialog.restore_windows()

    def _reset_rapid_clicks(self):
        """连续点击计时窗超时 → 计数清零（间隔太久不算「连续」）。"""
        self._rapid_clicks = 0

    def _on_angry(self):
        """连续左键点击 5 次 → 触发生气动画 + 生气台词。"""
        self._play_sprite_anim("angry")
        self._show_bubble("angry")

    def _ensure_chat_dialog(self):
        """确保聊天对话框已创建（惰性创建，首次左键/拖拽时建）。
        创建后永久复用，closeEvent 会拦截关闭改为隐藏。"""
        if self._chat_dialog is not None:
            return
        from tamias.chat_dialog import ChatDialog
        self._chat_dialog = ChatDialog(
            pet_name="栗栗",
            parent=None,  # 独立窗口，显示在任务栏
            on_message=self._on_chat_message,
            pro_mode=self._pro_mode,
            conv_store=self._conv_store,
            settings=self._settings,
            refresh_dsh=self._refresh_dsh,
            dsh_status=self._dsh_status,
            on_cancel_work=self._on_cancel_work,
        )
        self._chat_dialog.folder_opened.connect(self.working_dir_changed.emit)
        self._chat_dialog.mode_switch_requested.connect(self._on_mode_switch_requested)
        self._chat_dialog.status_changed.connect(self._on_chat_status)
        # 加载当前项目的历史
        work_dir = self._settings.get("work_dir", "") if self._settings else ""
        if self._conv_store:
            self._chat_dialog.refresh_history(self._conv_store, work_dir)

    def _on_drop_files(self, paths):
        """文件/文件夹拖到栗栗身上 → 解析成项目文件夹 → 切专业模式并打开项目。"""
        from tamias.workspace import resolve_project_folder
        folder = resolve_project_folder(paths)
        if not folder:
            return
        # 拖进来就是「干活」意图：先切专业模式（若还不是），再打开项目
        if not self._pro_mode:
            self.set_pro_mode(True)
        self._ensure_chat_dialog()
        if self._chat_dialog.open_project_folder(folder):
            # 首次拖拽时聊天窗可能刚建好还没显示（或已最小化），open 只切了内部页面、
            # 窗口本身没浮到前台，得显式还原一次——否则用户看到「没反应」，
            # 还得再点一下栗栗才出来（老 bug：未左键打开过任何界面时拖文件夹不生效）。
            self._chat_dialog.restore_windows()

    # ---------- 对话气泡 ----------

    def _show_bubble(self, kind: str):
        """在皮套头顶上方偏左弹一句漫画式对话气泡。kind = greeting（问候）/ poked（被戳）。"""
        from tamias.bubble import pick
        self._show_text(pick(kind))

    def _show_text(self, text: str):
        """直接弹一句指定文案的气泡（陪伴提醒 / 主动搭话用）。"""
        if not self.isVisible():
            return  # 皮套隐藏中：气泡是独立窗口，弹了会孤零零留在原位置
        if self._bubble is None:
            from tamias.bubble import BubbleWidget
            self._bubble = BubbleWidget()
        self._bubble.show_text(text, self.frameGeometry())

    def _on_water_reminder(self, text: str):
        """喝水提醒到点：弹气泡 + 播递水（water）动画（栗栗从右侧虚空掏出一瓶水递给你）。"""
        self._show_text(text)
        self._play_sprite_anim("water")

    def _on_chat_status(self, text: str):
        """聊天框标题栏状态文字（正在思考/搜索…）→ 皮套头顶气泡镜像显示；空则隐藏。
        让用户没盯着聊天框时，也能从皮套旁看到栗栗正在忙。"""
        if self._bubble is None:
            from tamias.bubble import BubbleWidget
            self._bubble = BubbleWidget()
        if self.isVisible():
            # 皮套可见才同步气泡；隐藏时气泡（独立窗口）会孤零零留在原位置，不弹
            if text:
                self._bubble.show_status(text, self.frameGeometry())
            else:
                self._bubble.hide_status()
        # 被要求搜索（web_search / web_fetch）→ 播一次「搜索」动画
        if text and text in (tr("正在上网搜集资料…"), tr("正在上网浏览网页…")):
            self._play_sprite_anim("search")
        # 被要求定位文件（glob / grep）→ 播一次「掏文件夹」动画
        if text == tr("正在搜索文件…"):
            self._play_sprite_anim("folder")
        # 执行命令（bash/pwsh）→ 播「拿对讲机」进入动画；状态离开「执行命令」则停掉恢复
        if text == tr("正在执行命令…"):
            if not self._executing:
                self._executing = True
                self._play_sprite_anim("exec_cmd")
        elif self._executing:
            # 命令结束：只在当前还在播执行命令动画时才停（别误停 folder/search 等）
            self._executing = False
            if self._playing_anim in ("exec_cmd", "exec_cmd_loop"):
                self._stop_exec_anim()
        # 社区动作 mod：内置没处理的「状态文字」→ 播社区动作（如读/写/编辑文件）
        if text and text in self._mod_status:
            name = self._mod_status[text]
            meta = self._mod_meta.get(name) or {}
            self._play_sprite_anim(name, loop=meta.get("loop", False),
                                   ping_pong=meta.get("ping_pong", False))

    def _on_reminder(self, text: str):
        """定时提醒到点：弹桌宠气泡 + 提示音（托盘通知由 main.py 接同一个信号补）。"""
        self._show_text(tr("⏰ 时间到：{}", text or tr("时间到啦～")))
        QApplication.beep()

    def _show_startup_bubble(self):
        """启动时弹一句问候气泡。"""
        self._show_bubble("greeting")

    # ---------- 精灵帧动画（打哈欠/看书=空闲触发 / 被戳=点击触发） ----------

    def _reset_idle(self):
        """用户交互后：重置所有空闲计时（打哈欠 + 看书都推后）。"""
        now = time.monotonic()
        self._last_activity = now
        self._yawn_interval = self._pick_yawn_interval()
        self._last_book = now
        self._book_interval = self._pick_book_interval()

    def _pick_yawn_interval(self) -> float:
        """抽一次打哈欠间隔。设了 TAMIAS_YAWN_TEST_SECONDS 就用固定秒数（真机测试），否则 30 秒~1 分钟随机。"""
        if _YAWN_TEST_SECONDS:
            try:
                return float(_YAWN_TEST_SECONDS)
            except ValueError:
                pass
        return random.uniform(30, 60)

    def _pick_book_interval(self) -> float:
        """抽一次看书间隔：3~5 分钟随机。
        注：看书动画右边还有条深色边没裁干净，属已知缺陷；先靠拉长触发间隔减少被用户撞见的概率，以后再修。"""
        return random.uniform(180, 300)

    def _scan_mod_actions(self):
        """扫描社区 mod 目录（%APPDATA%\\Tamias\\mods\\animations）下的动作包，建索引。
        社区动作 = 一个目录（透明 PNG 序列 + manifest.json），丢进 mod 目录即生效，不用改代码。
        三类口子：
          - replace：点名替换内置动作（{"replace": "search"} → 内置「搜索」改用这个动作的帧）
          - triggers.status：新增「状态文字 → 动作」（{"type":"status","status":"正在读取文件…"}）
          - triggers.idle：新增空闲动作（{"type":"idle","min_sec":1800,"max_sec":3600}，静置区间内随机播）
        播放参数：loop（循环）、ping_pong（正反往复）、offset（dx/dy 位置微调）都从 manifest 读，缺省 false/0。
        """
        app_paths.ensure_mods_dir()  # 首次启动自动建 mod 目录 + 生成 README 制作说明
        anim_root = str(app_paths.get_mods_dir() / "animations")
        if not os.path.isdir(anim_root):
            return
        # 内置已占用的状态文字，社区不能重复声明（避免和 search/folder/exec_cmd 抢触发）
        builtin_status = {
            tr("正在上网搜集资料…"), tr("正在上网浏览网页…"),
            tr("正在搜索文件…"), tr("正在执行命令…"),
        }
        now = time.monotonic()
        for name in sorted(os.listdir(anim_root)):
            mpath = os.path.join(anim_root, name, "manifest.json")
            if not os.path.isfile(mpath):
                continue
            try:
                with open(mpath, "r", encoding="utf-8") as fp:
                    m = json.load(fp)
                if not isinstance(m, dict):
                    continue
                rep = m.get("replace")
                trigs = m.get("triggers") or []
                if not rep and not trigs:
                    continue  # 内置动作（无 replace/triggers），不进 mod 索引
                off = m.get("offset") or {}
                if not isinstance(off, dict):
                    off = {}
                self._mod_meta[name] = {
                    "loop": bool(m.get("loop", False)),
                    "ping_pong": bool(m.get("ping_pong", False)),
                    "dx": int(off.get("dx", 0) or 0),
                    "dy": int(off.get("dy", 0) or 0),
                    "dir": os.path.join(anim_root, name),  # 社区动作的实际磁盘路径
                }
                if rep:
                    self._mod_replace[rep] = name
                for t in trigs:
                    if not isinstance(t, dict):
                        continue
                    ttype = t.get("type")
                    if ttype == "status":
                        status = t.get("status")
                        if status and status not in builtin_status:
                            self._mod_status[status] = name
                    elif ttype == "idle":
                        mn = float(t.get("min_sec", 1800) or 1800)
                        mx = float(t.get("max_sec", 3600) or 3600)
                        if mx < mn:
                            mx = mn
                        self._mod_idle.append({
                            "anim": name,
                            "min_sec": mn,
                            "max_sec": mx,
                            "next_at": now + random.uniform(mn, mx),
                        })
            except Exception:
                continue  # 单个动作包坏了（manifest 字段异常等）→ 跳过它，不影响其它包和启动

    def _get_sprite(self, anim_name: str):
        """懒加载指定动画的精灵播放器（yawn / poke / reading），首次触发时才建（省启动时间/内存）。"""
        sprite = self._sprites.get(anim_name)
        if sprite is None:
            from tamias.sprite_player import SpritePlayer
            # replace：社区点名替换内置动作 → 实际加载社区目录（逻辑名不变，衔接/状态判断照旧）
            target = self._mod_replace.get(anim_name, anim_name)
            meta = self._mod_meta.get(target)
            if meta is not None:
                # 社区动作：从 mod 目录加载（AppData 可写、卸载/升级不丢）
                anim_dir = meta["dir"]
            else:
                # 内置动作：从程序目录 resources/animations 加载
                anim_dir = os.path.join(os.path.dirname(__file__), "resources", "animations", target)
            sprite = SpritePlayer(
                anim_dir,
                self.centralWidget(),
                display_scale=0.975,  # 角色整体缩到 97.5%（相对 Live2D 微调大小）
            )
            sprite.finished.connect(self._on_sprite_finished)
            # 精灵逻辑尺寸居中放：窗口 200 宽，左右各留 ~21px（0.95 缩放后约 26px）
            # 精灵动画统一往左下角微调（用户反馈位置有点偏移，被戳 poke 除外）；dx 负=往左，dy 正=往下
            # 位置微调：dx 负=往左、正=往右；dy 正=往下。
            # hand_wait / exec_cmd_loop 往右 5px（夹纸板/循环对讲机动作手在右侧，整体略左）
            # exec_cmd（进入动画）往左 5px（用户看效果后单独微调）
            if meta is not None:
                # 社区动作：位置偏移来自 manifest 的 offset
                dx, dy = meta["dx"], meta["dy"]
            else:
                # 内置动作：位置微调硬编码（dx 负=往左、dy 正=往下）
                if anim_name in ("hand_wait", "exec_cmd_loop"):
                    dx, dy = 5, 0
                elif anim_name == "exec_cmd":
                    dx, dy = -5, 0
                elif anim_name in ("search", "reading", "yawn", "pinch_left", "pinch_right", "angry", "hand_touch"):
                    dx, dy = -2, 2
                else:
                    dx, dy = 0, 0
            sprite.move(
                (WIDGET_WIDTH - sprite.width()) // 2 + dx,
                WIDGET_HEIGHT - sprite.height() + dy,
            )
            self._sprites[anim_name] = sprite
        return sprite

    def _on_task_started(self):
        """干活真正开始（main.py work_handler 发 task_started）→ 播一次「闭眼思考」动画。
        只在真开干时播，闲聊不播。"""
        self._play_sprite_anim("think")

    def _on_approval_waiting(self):
        """审批开始：栗栗递出夹纸板等主人点批准/拒绝。
        递出播完若还没决，_on_sprite_finished 会切 hand_wait 循环等待。"""
        self._approval_pending = True
        self._play_sprite_anim("hand_over")

    def _on_approval_done(self):
        """审批结束：停掉循环等待，恢复 Live2D。"""
        self._approval_pending = False
        if self._playing_sprite is not None and self._playing_sprite.is_playing:
            self._playing_sprite.stop()   # 停 hand_wait 循环（loop 模式不发 finished）
        self._playing_sprite = None
        self._playing_anim = None
        self.pet_widget.show()

    def _stop_exec_anim(self):
        """命令结束：停掉执行命令的通话动画（含停在末帧待机的情况），恢复 Live2D。"""
        if self._playing_sprite is not None:
            self._playing_sprite.stop()   # 停 timer + hide（即使停在末帧，也确保隐藏）
            self._playing_sprite = None
        self._playing_anim = None
        self.pet_widget.show()

    def _play_sprite_anim(self, anim_name: str, loop: bool = False,
                          loop_count: int | None = None, ping_pong: bool = False):
        """播一段精灵动画：盖住 Live2D，播完 _on_sprite_finished 恢复（loop=True 则循环直到 stop）。
        已有动画在播则先停掉旧的（不叠播）。"""
        if self._playing_sprite is not None and self._playing_sprite.is_playing:
            self._playing_sprite.stop()  # stop 不发 finished，状态由 _playing_sprite 管
            # 打断的若是告别动画（stop 不发 finished、告别流程走不到渐隐结束），
            # 这里复位 _disappearing，否则卡 True → show_with_animation 永远 return，
            # 立绘再也显示不出来（隐藏后点托盘打不开的根因之一）
            if self._playing_anim == "disappear":
                self._disappearing = False
                self._after_disappear = None
        sprite = self._get_sprite(anim_name)
        self._playing_sprite = sprite
        self._playing_anim = anim_name   # 记下在播哪个，播完只重置它自己的空闲计时
        self.pet_widget.hide()
        sprite.play(loop=loop, loop_count=loop_count, ping_pong=ping_pong)
        self._overlay.raise_()   # 透明覆盖层压回最上，动画期间点击仍走聊天

    def _on_sprite_finished(self):
        """任一段精灵动画播完 → 恢复 Live2D，只重置「刚播完这个动画」自己的空闲计时。
        例外：disappear（告别）播完不恢复立绘，直接接窗口渐隐，渐隐结束走回调。"""
        if self._playing_anim == "disappear":
            cb = self._after_disappear
            self._playing_sprite = None
            self._playing_anim = None
            self._after_disappear = None
            self._fade_out_then(cb)
            return
        # 递出审批播完 → 主人还没点，切循环等待（摇尾巴）
        if self._playing_anim == "hand_over" and self._approval_pending:
            self._play_sprite_anim("hand_wait", loop=True)
            return
        # 执行命令进入动画播完 → 还在执行，切循环通话（往返循环 3 圈）
        if self._playing_anim == "exec_cmd" and self._executing:
            self._play_sprite_anim("exec_cmd_loop", loop=True, loop_count=3, ping_pong=True)
            return
        # 循环通话够了 → 不单独 return，走下面通用逻辑恢复立绘（命令还在执行也先停，不一直播）
        self._playing_sprite = None
        self.pet_widget.show()
        now = time.monotonic()
        if self._playing_anim == "reading":
            # 看书播完：只推后看书，别打乱打哈欠节奏
            self._last_book = now
            self._book_interval = self._pick_book_interval()
        elif self._playing_anim == "yawn":
            # 打哈欠播完：只推后打哈欠，别影响看书
            self._last_activity = now
            self._yawn_interval = self._pick_yawn_interval()
        else:
            # poke 是用户点击触发，播完当作用户交互，两个空闲计时都推后
            self._reset_idle()
        self._playing_anim = None

    def _check_idle(self):
        """空闲超时 → 打哈欠 / 看书（各配一句气泡台词）。正在播动画 / 有气泡显示时跳过，等下个 tick 再说。"""
        if self._playing_sprite is not None and self._playing_sprite.is_playing:
            return
        if self._bubble is not None and self._bubble.isVisible():
            return
        # 精神值（SAN）：半夜掉到阈值优先触发困倦（触发后本次直接返回，别又抢打哈欠/看书）
        if self._check_sleepy():
            return
        now = time.monotonic()
        # 看书间隔更长、更稀，优先判断，避免被频繁打哈欠顶掉
        if now - self._last_book >= self._book_interval:
            self._play_sprite_anim("reading")
            self._show_bubble("reading")
        elif now - self._last_activity >= self._yawn_interval:
            self._play_sprite_anim("yawn")
            self._show_bubble("yawn")
        else:
            # 社区动作 mod：内置空闲动作没触发时，查社区 idle 动作到点没
            for item in self._mod_idle:
                if now >= item["next_at"]:
                    meta = self._mod_meta.get(item["anim"]) or {}
                    self._play_sprite_anim(item["anim"], loop=meta.get("loop", False),
                                           ping_pong=meta.get("ping_pong", False))
                    item["next_at"] = now + random.uniform(item["min_sec"], item["max_sec"])
                    break

    # ---------- 精神值（SAN）系统 ----------

    def _san_value(self) -> int:
        """当前精神值（0~100）：白天恒满 100；半夜 2:00~6:00 随夜深线性掉到 0。

        纯时间函数（本地时间），关掉重开 = 睡醒，直接回满。"""
        now = datetime.now()
        h = now.hour + now.minute / 60.0 + now.second / 3600.0
        if 2.0 <= h < 6.0:
            return int(max(0.0, 100.0 - (h - 2.0) / 4.0 * 100.0))
        return 100

    def _check_sleepy(self) -> bool:
        """半夜精神值掉到阈值 → 播困倦动画 + 台词（每个档位只触发一次）。返回是否已触发。

        触发档位：≤30 首次，之后每再掉 20 点一次（30 → 10）。素材「sleepy」没生成前，
        播动画会因无帧立即结束（SpritePlayer 静默跳过），台词照常弹。"""
        san = self._san_value()
        for threshold in (30, 10):
            if san <= threshold and self._last_sleepy_san != threshold:
                self._last_sleepy_san = threshold
                self._play_sprite_anim("sleepy")
                self._show_bubble("night_sleepy")
                return True
        # 精神值回满（白天/睡醒）→ 清档位记忆，下个深夜又能从 30 档重新触发
        if san >= 100:
            self._last_sleepy_san = None
        return False

    def _on_hover_timeout(self):
        """悬停满 2.5 秒 → 在头顶弹精神值进度条。"""
        self._show_spirit_meter()

    def _show_spirit_meter(self):
        """懒加载精神值进度条气泡，显示当前 SAN。"""
        if self._spirit_meter is None:
            from tamias.spirit_meter import SpiritMeter
            self._spirit_meter = SpiritMeter()
        self._spirit_meter.show_value(self._san_value(), self.frameGeometry())

    def _hide_spirit_meter(self):
        """收起精神值进度条气泡。"""
        if self._spirit_meter is not None:
            self._spirit_meter.hide()

    # ---------- 公共属性 ----------

    @property
    def chat_dialog(self):
        """聊天对话框实例（首次点击桌宠才创建，可能为 None）。"""
        return self._chat_dialog

    @property
    def always_work(self) -> bool:
        """是否处于"始终干活"模式"""
        return self._always_work

    @always_work.setter
    def always_work(self, value: bool):
        self.set_work_mode(value)

    @property
    def pro_mode(self) -> bool:
        """是否处于专业模式"""
        return self._pro_mode

    @property
    def auto_start(self) -> bool:
        """是否已开启开机自启动（直接查注册表 Run 键）。"""
        from tamias import auto_start
        return auto_start.is_enabled()

    @property
    def language(self) -> str:
        """当前界面语言（zh-CN/zh-TW/en/ja）"""
        return self._settings.language if self._settings else "zh-CN"


# ============================================================
# 模块级测试
# ============================================================
if __name__ == "__main__":
    print("启动栗栗桌宠窗口测试...")
    print("左键点击 → 聊天 | 右键点击 → 菜单")
    print("拖拽 → 移动 | 右键菜单 → 退出")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.show_with_animation()
    sys.exit(app.exec())
