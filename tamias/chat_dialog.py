# ============================================================
# 栗栗（Tamias）— 聊天对话框
# ============================================================
# 支持两种主题：粉色气泡 ｜ VS Code 终端风格（专业模式）
# ============================================================

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea,
    QTextEdit, QPushButton, QWidget, QLabel, QSizePolicy, QFileDialog,
    QCheckBox, QMessageBox, QSplitter, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices, QKeySequence, QShortcut, QTextCursor
import os
import html
import re
from datetime import datetime

from tamias.project_store import CHITCHAT_PROJECT_ID
from tamias.workspace import is_drive_root
from tamias.i18n import tr
from tamias.fonts import ui_font, mono_font
from tamias.theme import PRO_THEME_ORDER, DEFAULT_PRO_THEME, IS_DARK
from tamias.viewer_panel import ViewerPanel
from tamias.ui_icons import apply_icon, icon, strip_leading_emoji
from tamias.speech_input import SpeechInput
from tamias.chat_widgets import ReplyWorker, AnimatedButton, SlideStack, PlanCard


# ---------- 功能开关 ----------
# 「发送审查」多实例协作（AgentBus 文件总线）：暂缓关闭（2026-08-20）。
# 没时间完善它，先把入口失效 + 停掉轮询；完整背景见 future-plans.md。
# 要恢复：改回 True 即可（按钮/轮询/收发逻辑都还在，只是被这个开关关掉）。
AGENT_BUS_ENABLED = False


# ---------- 常量 ----------
DIALOG_WIDTH = 460   # 普通模式窗口宽（电脑屏阅读，比手机尺寸调大）
DIALOG_HEIGHT = 600  # 普通模式窗口高
DIALOG_WIDTH_PRO = 1360  # 专业模式更宽（聊天 + 项目面板 + 留白；审批已改内联卡片，不再占常驻列）
DIALOG_HEIGHT_PRO = 720  # 专业模式更高，给消息区+预览区更多纵向空间
INPUT_HEIGHT = 60
MAX_PENDING_QUEUE = 3   # 排队上限：最多同时排 3 条，满了提示等干完再发
QUEUE_TEXT_MAX = 20     # 队列面板里每条消息最多显示字数，超长截断
BUBBLE_MAX_WIDTH = 380  # 普通模式气泡最大宽（随窗口一起调大，减少换行）
BUBBLE_MAX_WIDTH_PRO = 780  # 专业模式终端块最大宽（约消息区可用宽度，占满不再「几个字换行」）

# 普通模式配色：暖棕侦探风（呼应栗栗「松鼠侦探管家 + 猎鹿帽 + 格纹风衣」，
# 气质锚「清澈大学生」——温暖、干净、书卷气，不再是粉嫩少女风）
COLOR_USER_BUBBLE = "#A9745B"   # 用户气泡：栗棕/焦糖
COLOR_AI_BUBBLE = "#FFFDF7"     # 栗栗气泡：暖奶白
COLOR_BG = "#F5EDE1"            # 背景：暖羊皮纸米白
COLOR_USER_TEXT = "#FFFFFF"     # 用户文字：白
COLOR_AI_TEXT = "#463329"       # 栗栗文字：深咖
COLOR_INPUT_BG = "#FFFFFF"      # 输入框背景
COLOR_SEND_BTN = "#A9745B"      # 发送按钮：栗棕


class ChatDialog(QDialog):
    """聊天对话框，粉色主题 / VS Code 终端风格（专业模式）。"""
    folder_opened = Signal(str)
    stream_text = Signal(str)   # 流式增量信号：后台线程 emit → 主线程逐段更新气泡（打字机）
    status_text = Signal(str)   # 状态信号：后台线程 emit → 主线程更新标题栏「正在干嘛」
    work_changed = Signal(list) # 干活回滚信号：后台线程 emit 本次改动文件清单 → 主线程弹「这次改了 N 个文件」入口
    step_event = Signal(str, str)  # 步骤信号：后台线程 emit (state, label) → 主线程渲染「过程列表」
    todo_event = Signal(list)      # 计划清单信号：后台线程 emit (todos) → 主线程渲染「计划卡」
    usage_event = Signal(dict) # token 用量信号：后台线程 emit usage → 主线程累加显示「本轮已用 X tokens」
    mode_switch_requested = Signal()  # 启动器「专业模式/普通模式」按钮被点 → 请求切到另一模式（pet_window 统一切换 + 持久化）
    status_changed = Signal(str)  # 对外状态信号：标题栏状态文字变化（含空=结束），桌宠气泡镜像显示「思考/搜索中」

    def __init__(self, pet_name: str = "栗栗", parent=None, on_message=None,
                 pro_mode: bool = False, conv_store=None, settings=None,
                 refresh_dsh=None, dsh_status=None, on_cancel_work=None):
        super().__init__(parent)
        self._pet_name = pet_name
        self._on_message_callback = on_message
        self._waiting = False
        self._worker = None
        self._pending_queue = []  # 排队队列：忙时按回车入队，干完自动依次处理（学 Claude Code）
        self._current_task_text = ""  # 当前正在处理的任务原文（队列面板「正在处理」行显示用）
        self._failed_task = ""  # 失败停住的任务原文（非空 = 处于「失败待处置」态，排队暂停）
        self._thinking_idx = -1
        self._stream_idx = -1        # 正在流式显示的气泡索引（-1 = 无/尚未创建）
        self._stream_buffer = ""     # 累积的流式文本
        self._stream_started = False # 是否已收到首个流式增量（用于覆盖占位文字）
        self._stream_waiting = False # 是否在等待回复（发送后 True，完成/取消后 False）
        self._pro_mode = pro_mode
        # 专业模式主题（dark=深色现状 / warm=暖棕）；从配置读取上次选择，重启后记住
        _saved_theme = settings.get("pro_theme", DEFAULT_PRO_THEME) if settings else DEFAULT_PRO_THEME
        self._pro_theme = _saved_theme if _saved_theme in PRO_THEME_ORDER else DEFAULT_PRO_THEME
        self._pending_plan_msg = None
        self._working_dir = ""
        self._conv_store = conv_store
        self._settings = settings
        self._refresh_dsh = refresh_dsh  # 手动刷新 dsh 回调（后台线程跑，返回是否成功）
        self._dsh_status = dsh_status    # 查询 dsh 连接状态回调（'ok'/'down'）
        self._on_cancel_work = on_cancel_work  # 「终止」干活回调（真正打断 dsh 线程）
        self._current_conv = None
        self._gate_event = None       # 门禁审批等待事件（后台线程 wait 用）
        self._gate_approved = False   # 门禁审批结果（True=批准）
        self._approval_card = None      # 内联审批卡片（聊天流里临时插入，答完即删；见 _activate_approval）
        self._approval_approve_btn = None  # 卡片上的批准按钮（键盘 1 快捷键要查它）
        self._approval_reject_btn = None   # 卡片上的拒绝按钮（键盘 2 快捷键要查它）
        self._question_card = None      # 内联反问卡片（聊天流里临时插入，答完即删；见 _activate_question）
        self._gate_question_event = None  # 反问等待事件（后台线程 wait 用）
        self._gate_question_answers = []  # 反问答案列表（选完 set Event 后由后台线程读）
        self._question_rows = []        # 每问「怎么收集答案」的控件引用（提交时读）
        self._current_project = None  # 当前所在项目
        self._is_project_store = hasattr(conv_store, 'create_project') if conv_store else False
        self._changes_chip = None    # 「这次改了 N 个文件」可点击入口（每次干活后刷新，旧的要先删）
        self._step_list = None       # 当前这一轮干活的过程列表控件（None=还没开始；新轮次在 _on_send 里重置）
        self._plan_card = None       # 当前这一轮干活的计划卡控件（None=还没开始；新轮次在 _on_send 里重置）
        self._task_tokens = 0        # 本轮累计 token（干活逐条累加真实值 + 闲聊结束校准真实值），_send_text 里重置
        # 实时秒表 + token：栗栗一动作就起表，元信息挂在「栗栗回复右侧」（见 _start_elapsed / _refresh_meta）
        self._elapsed_seconds = 0
        self._token_est = 0      # 闲聊 token 估算值（没拿到真实 usage 前用 ≈N）
        self._meta_widgets = []  # 本轮回复右侧的元信息承载控件（气泡/过程列表对象，可能多个）
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self.setWindowTitle(tr("和{}聊天", tr(pet_name)))
        w = DIALOG_WIDTH_PRO if pro_mode else DIALOG_WIDTH
        h = DIALOG_HEIGHT_PRO if pro_mode else DIALOG_HEIGHT
        self.resize(w, h)
        self.setMinimumSize(300, 300)  # 允许最大化
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setWindowState(Qt.WindowState.WindowNoState)  # 允许最大化

        self._init_ui()
        self._apply_theme()

        self._messages: list[dict] = []
        self.stream_text.connect(self._on_stream_text)  # 流式增量 → 原地更新气泡
        self.status_text.connect(self._on_status_text)  # 状态文字 → 标题栏「正在干嘛」
        self.work_changed.connect(self._on_work_changed)  # 干活回滚 → 弹「这次改了 N 个文件」入口
        self.step_event.connect(self._on_step_event)  # 过程步骤 → 聊天流罗列每一步
        self.todo_event.connect(self._on_todo_event)  # 计划清单 → 聊天流渲染「计划卡」
        self.usage_event.connect(self._on_usage_event)  # token 用量 → 过程列表累加显示
        self._position_near_pet()
        self._add_welcome_message()

    # ==================== UI 构建 ====================

    def _init_ui(self):
        self._stack = SlideStack()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._stack)

        # ====== 第0页：启动器（左右两半）======
        self._launcher = QWidget()
        # 主题切换（「主题风格」+ 两个小圆点）：仅专业模式显示，放启动器右上角
        self._theme_switch_bar = self._build_theme_switch()
        # 外层垂直布局：顶部右对齐放主题切换，下面放原来的左右两半
        outer = QVBoxLayout(self._launcher)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 14, 22, 0)
        top_bar.addStretch()
        top_bar.addWidget(self._theme_switch_bar)
        outer.addLayout(top_bar)
        self._launcher_layout = QHBoxLayout()
        self._launcher_layout.setContentsMargins(0, 0, 0, 0); self._launcher_layout.setSpacing(0)
        outer.addLayout(self._launcher_layout, stretch=1)

        # === 底部：模式切换按钮（两种模式都显示，次级小按钮，放右下角） ===
        # 普通模式显示「⚡专业模式」、专业模式显示「普通模式」；点它发 mode_switch_requested，
        # 由 pet_window 统一调 set_pro_mode 切换（会回启动器 + 持久化到 settings，重启后记住）。
        mode_bar = QHBoxLayout()
        mode_bar.setContentsMargins(0, 0, 18, 14)
        mode_bar.addStretch()
        self._mode_btn = apply_icon(QPushButton(), "zap", tr("专业模式"), size=14)
        self._mode_btn.setFont(ui_font(11))
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setToolTip(tr("有正事要办？切到专业模式，让我来帮你办"))
        self._mode_btn.clicked.connect(lambda: self.mode_switch_requested.emit())
        mode_bar.addWidget(self._mode_btn)
        outer.addLayout(mode_bar)

        # === 左半：选项区 ===
        self._launcher_left = QWidget()
        left_layout = QVBoxLayout(self._launcher_left)
        left_layout.setContentsMargins(40, 30, 20, 30); left_layout.setSpacing(10)

        self._launcher_title = QLabel(tr("栗栗")); self._launcher_title.setFont(ui_font(22, bold=True))
        self._launcher_title.setStyleSheet("color:#CCC;"); left_layout.addWidget(self._launcher_title)
        self._launcher_sub = QLabel(tr("桌面智能助手")); self._launcher_sub.setFont(ui_font(12))
        self._launcher_sub.setStyleSheet("color:#888;"); left_layout.addWidget(self._launcher_sub)
        left_layout.addSpacing(15)

        bs = ("background:#1A1A1A;color:#CCC;border:1px solid #444;"
              "border-radius:6px;padding:12px;font-family: 'HarmonyOS Sans SC';font-size:13px;"
              "text-align:left;margin-left:{offset};")
        self._btn_free = apply_icon(AnimatedButton(tr("💬  日常闲聊\n随便聊聊，自动帮你存下来")), "message-circle", tr("💬  日常闲聊\n随便聊聊，自动帮你存下来"), size=22)
        self._btn_free._base_style = bs; self._btn_free.setStyleSheet(bs.replace("{offset}","0px")); self._btn_free.clicked.connect(lambda: self._enter_chitchat()); left_layout.addWidget(self._btn_free)
        self._btn_open = apply_icon(AnimatedButton(tr("📂  打开文件夹\n新建 / 继续一个项目")), "folder-open", tr("📂  打开文件夹\n新建 / 继续一个项目"), size=22)
        self._btn_open._base_style = bs; self._btn_open.setStyleSheet(bs.replace("{offset}","0px")); self._btn_open.clicked.connect(self._open_folder); left_layout.addWidget(self._btn_open)
        self._btn_usage = apply_icon(AnimatedButton(tr("📖  使用说明\n怎么和我聊天、让我干活")), "book-open", tr("📖  使用说明\n怎么和我聊天、让我干活"), size=22)
        self._btn_usage._base_style = bs; self._btn_usage.setStyleSheet(bs.replace("{offset}","0px")); self._btn_usage.clicked.connect(self._on_usage); left_layout.addWidget(self._btn_usage)

        left_layout.addSpacing(10)
        self._recent_label = QLabel(tr("最近")); self._recent_label.setFont(ui_font(11, bold=True)); self._recent_label.setStyleSheet("color:#666;"); left_layout.addWidget(self._recent_label)
        from PySide6.QtWidgets import QListWidget
        self._recent_list = QListWidget()
        self._recent_list.setStyleSheet("QListWidget{background:#0D0D0D;border:1px solid #333;color:#CCC;font-size:11px;}QListWidget::item{padding:6px;border-bottom:1px solid #222;}QListWidget::item:hover{background:#1A1A1A;}")
        self._recent_list.itemClicked.connect(self._on_recent_clicked)
        # 右键菜单：删除 / 重命名 / 置顶（★）
        self._recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._recent_list.customContextMenuRequested.connect(self._on_recent_context_menu)
        left_layout.addWidget(self._recent_list, stretch=1)
        self._launcher_left.setMaximumWidth(380)
        self._launcher_layout.addWidget(self._launcher_left, stretch=0)
        self._launcher_layout.addStretch(1)

        # === 右半：欢迎区 ===
        self._launcher_right = QWidget()
        self._launcher_right.setStyleSheet("background:#0A0A0A; border-left:1px solid #222;")
        self._launcher_right_layout = QVBoxLayout(self._launcher_right)
        self._launcher_right_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_lb = QLabel(tr("欢迎回来"))
        self._welcome_lb.setFont(ui_font(20))
        self._welcome_lb.setStyleSheet("color: #333;")
        self._welcome_lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._launcher_right_layout.addWidget(self._welcome_lb)
        self._hint_lb = QLabel(tr("（栗栗图案位置）"))
        self._hint_lb.setFont(ui_font(10))
        self._hint_lb.setStyleSheet("color: #2A2A2A;")
        self._hint_lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._launcher_right_layout.addWidget(self._hint_lb)
        self._launcher_layout.addWidget(self._launcher_right, stretch=1)

        self._stack.addWidget(self._launcher)  # index 0

        # ====== 第1页：聊天界面 ======
        self._chat_page = QWidget()
        main_layout2 = QVBoxLayout(self._chat_page)
        main_layout2.setContentsMargins(10, 10, 10, 10)
        main_layout2.setSpacing(8)
        self._stack.addWidget(self._chat_page)  # index 1
        main_layout = main_layout2  # 后面代码用 main_layout = 聊天页布局

        # 标题栏
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 0, 0, 0)
        title_bar.setSpacing(2)

        # 返回启动页按钮
        self._back_btn = QPushButton("←")
        self._back_btn.setFixedSize(24, 24)
        self._back_btn.setFont(mono_font(12))
        self._back_btn.setToolTip(tr("返回首页"))
        self._back_btn.clicked.connect(lambda: self._slide_to(0))
        self._back_btn.setStyleSheet("QPushButton{background:transparent;color:#888;border:1px solid #444;border-radius:3px;}QPushButton:hover{color:#fff;}")
        self._back_btn.setVisible(True)  # 返回按钮所有模式都显示（普通模式进去也要能出来）
        title_bar.addWidget(self._back_btn)

        # 「栗栗」标题 + 右侧状态（等待回复期间显示「正在干嘛」，
        # 替代以前塞在对话里的「请稍等」占位气泡——状态放标题栏，对话里干净）。
        title_center = QHBoxLayout()
        title_center.setContentsMargins(0, 0, 0, 0)
        title_center.setSpacing(8)
        self._title_label = QLabel(tr("栗栗"))
        self._title_label.setFont(ui_font(12, bold=True))
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label = QLabel("")
        self._status_label.setFont(ui_font(9))
        self._status_label.setStyleSheet("color:#7A5540;")  # 暖棕（普通模式默认色，_apply_theme 会覆盖）
        self._status_label.setVisible(False)
        title_center.addStretch()
        title_center.addWidget(self._title_label)
        title_center.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        title_center.addStretch()
        title_bar.addLayout(title_center, stretch=1)

        # 摇人按钮
        self._call_btn = apply_icon(QPushButton(), "phone", tr("📞"), size=16)
        self._call_btn.setFixedSize(28, 28)
        self._call_btn.setFont(ui_font(10))
        self._call_btn.setToolTip(tr("摇人（团队合作）"))
        self._call_btn.setVisible(self._pro_mode)
        self._call_btn.clicked.connect(self._on_call)
        self._call_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #0f0; }
        """)
        title_bar.addWidget(self._call_btn)

        # 新对话按钮
        self._new_conv_btn = QPushButton("＋")
        self._new_conv_btn.setFixedSize(28, 28)
        self._new_conv_btn.setFont(ui_font(12, bold=True))
        self._new_conv_btn.setToolTip(tr("新对话"))
        self._new_conv_btn.setVisible(True)  # 所有模式都显示，普通用户也要能开新会话
        self._new_conv_btn.clicked.connect(self._on_new_conversation)
        self._new_conv_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #0f0; }
        """)
        title_bar.addWidget(self._new_conv_btn)

        self._folder_btn = apply_icon(QPushButton(), "folder-open", tr("📂"), size=16)
        self._folder_btn.setFixedSize(28, 28)
        self._folder_btn.setFont(ui_font(10))
        self._folder_btn.setToolTip(tr("打开文件夹"))
        self._folder_btn.setVisible(self._pro_mode)
        self._folder_btn.clicked.connect(self._on_open_folder)
        self._folder_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #fff; }
        """)
        title_bar.addWidget(self._folder_btn)

        # 历史记录按钮（闹钟图标）：点开下拉菜单切「当前项目」的旧对话
        self._history_btn = apply_icon(QPushButton(), "history", tr("🕐"), size=16)
        self._history_btn.setFixedSize(28, 28)
        self._history_btn.setFont(ui_font(10))
        self._history_btn.setToolTip(tr("历史记录"))
        self._history_btn.setVisible(True)  # 所有模式都显示（跟「＋新对话」配对）
        self._history_btn.clicked.connect(self._on_history_menu)
        self._history_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #fff; }
        """)
        title_bar.addWidget(self._history_btn)

        # 「隐藏/显示预览面板」开关（仅专业模式）：眼睛图标，点了收起/展开右侧查看器。
        # 测试员反馈：专业模式右侧查看器（文件树/日志/文档）占地方，想要能直接收起来。
        self._viewer_hidden = False  # 是否手动收起了右侧预览面板（默认展开）
        self._panel_btn = apply_icon(QPushButton(), "eye-off", tr("👁"), size=16)
        self._panel_btn.setFixedSize(28, 28)
        self._panel_btn.setFont(ui_font(10))
        self._panel_btn.setToolTip(tr("隐藏预览面板"))
        self._panel_btn.setVisible(self._pro_mode)
        self._panel_btn.clicked.connect(self._on_toggle_panel)
        self._panel_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #fff; }
        """)
        title_bar.addWidget(self._panel_btn)

        # 模式切换按钮（对话页顶部栏）：普通模式显示「⚡专业」、专业模式显示「普通」，
        # 点它发 mode_switch_requested，跟启动器右下角的 _mode_btn 走同一条切换链路
        # （回启动器 + 持久化）。让用户在项目界面里也能直接切模式，不必先回首页再切。
        self._page_mode_btn = QPushButton(tr("⚡专业"))
        self._page_mode_btn.setFixedSize(48, 28)
        self._page_mode_btn.setFont(ui_font(10, bold=True))
        self._page_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._page_mode_btn.setToolTip(tr("切到专业模式，让我来帮你办"))
        self._page_mode_btn.clicked.connect(lambda: self.mode_switch_requested.emit())
        self._page_mode_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #0f0; }
        """)
        title_bar.addWidget(self._page_mode_btn)

        main_layout.addLayout(title_bar)

        # 工作目录标签（仅专业模式显示）
        self._dir_label = QLabel("")
        self._dir_label.setFont(mono_font(8))
        self._dir_label.setStyleSheet("color: #666666; padding: 0 5px;")
        self._dir_label.setVisible(self._pro_mode)
        main_layout.addWidget(self._dir_label)

        # 正文区域：消息区 + 查看器面板（QSplitter 水平分割，可拖拽调宽）
        # （原左侧「历史/项目」侧边栏已删除：打开/新建/最近项目都归到启动器，见 future-plans）
        self._content_area = QSplitter(Qt.Orientation.Horizontal)
        self._content_area.setChildrenCollapsible(False)

        # --- 左侧消息区（包一层 QWidget，QSplitter 只吃 widget）---
        msg_area = QWidget()
        right_area = QVBoxLayout(msg_area)
        right_area.setContentsMargins(0, 0, 0, 0)
        right_area.setSpacing(0)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(8, 8, 8, 8)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()
        self._scroll_area.setWidget(self._msg_container)
        right_area.addWidget(self._scroll_area, stretch=1)

        # 附件显示条
        self._attachments_layout = QHBoxLayout()
        self._attachments_layout.setContentsMargins(4, 0, 4, 0)
        self._attachments_layout.setSpacing(4)
        right_area.addLayout(self._attachments_layout)

        self._content_area.addWidget(msg_area)

        # --- 右侧查看器面板（文件树/日志/文档，仅专业模式）---
        # 顶部常驻引擎状态条 + 「↩ 回滚」入口，下面 QTabWidget 切三页（见 viewer_panel.py）
        self._viewer = ViewerPanel(
            self._settings, self._refresh_dsh, self._dsh_status, parent=self)
        self._viewer.setVisible(self._pro_mode)
        self._viewer.rollback_requested.connect(self._open_rollback)
        self._viewer.conversation_selected.connect(self._load_conversation)
        self._content_area.addWidget(self._viewer)
        # 默认宽度比例：消息区宽一些，查看器约 520px（用户可拖分隔条调）
        self._content_area.setStretchFactor(0, 3)
        self._content_area.setStretchFactor(1, 2)
        # 初始尺寸明确按 3:2 分（否则 QSplitter 按 sizeHint 分，查看器 sizeHint 大，会把消息区挤没）
        self._content_area.setSizes([820, 540])

        main_layout.addWidget(self._content_area, stretch=1)

        # 输入区
        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        self._input_edit = QTextEdit()
        self._input_edit.setFixedHeight(INPUT_HEIGHT)
        self._input_edit.setPlaceholderText(tr("输入你想说的话..."))
        self._input_edit.setFont(ui_font(10))
        self._input_edit.installEventFilter(self)
        self.installEventFilter(self)  # 全局按键（1/2 批准拒绝）

        # 附件按钮（专业模式）
        self._attach_btn = QPushButton("＋")
        self._attach_btn.setFixedSize(34, INPUT_HEIGHT)
        self._attach_btn.setFont(ui_font(12, bold=True))
        self._attach_btn.setToolTip(tr("上传文件/图片"))
        self._attach_btn.setVisible(self._pro_mode)
        self._attach_btn.clicked.connect(self._on_attach)
        self._attach_btn.setStyleSheet("""
            QPushButton { background: #1A1A1A; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #0f0; }
        """)

        # 提示词库按钮（专业模式）：弹出常用指令词表，点选填入输入框。
        # 快捷键 Ctrl+P 等价触发（见下方 QShortcut）。
        self._prompt_btn = apply_icon(QPushButton(), "lightbulb", tr("💡"), size=16)
        self._prompt_btn.setFixedSize(34, INPUT_HEIGHT)
        self._prompt_btn.setToolTip(tr("提示词库（Ctrl+P）：常用指令一点就填"))
        self._prompt_btn.setVisible(self._pro_mode)
        self._prompt_btn.clicked.connect(self._open_prompt_library)
        self._prompt_btn.setStyleSheet("""
            QPushButton { background: #1A1A1A; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #0f0; }
        """)
        # Ctrl+P 打开提示词库（窗口内快捷键，跟 💡 按钮等效；父对象 self = 聊天框窗口）
        self._prompt_sc = QShortcut(QKeySequence("Ctrl+P"), self)
        self._prompt_sc.activated.connect(self._open_prompt_library)

        # 语音输入（按住说话 → Windows 本地离线识别 → 文字，零 token，音频不出本机）
        self._speech = SpeechInput(self)
        self._speech.text_ready.connect(self._on_speech_text)
        self._speech.error.connect(self._on_speech_error)

        # 语音输入按钮：按住说、松手出字（或按住 Alt 键说），所有模式都显示
        self._speech_btn = apply_icon(QPushButton(), "mic", tr("🎤"), size=16)
        self._speech_btn.setFixedSize(34, INPUT_HEIGHT)
        self._speech_btn.setToolTip(tr("按住说话，松手转文字（或按住 Alt 键说）"))
        self._speech_btn.setVisible(True)  # 所有模式都显示：不想打字是通用诉求
        self._speech_btn.pressed.connect(self._on_speech_press)
        self._speech_btn.released.connect(self._on_speech_release)
        self._speech_btn.setStyleSheet("""
            QPushButton { background: #1A1A1A; color: #888; border: 1px solid #444; border-radius: 4px; }
            QPushButton:hover { background: #333; color: #0f0; }
        """)

        self._send_btn = QPushButton(tr("发送"))
        self._send_btn.setFixedSize(60, INPUT_HEIGHT)
        self._send_btn.setFont(ui_font(10, bold=True))
        self._send_btn.clicked.connect(self._on_send_clicked)

        input_layout.addWidget(self._input_edit)
        input_layout.addWidget(self._attach_btn)
        input_layout.addWidget(self._prompt_btn)
        input_layout.addWidget(self._speech_btn)
        input_layout.addWidget(self._send_btn)

        # 附件存储
        self._pending_files: list[str] = []

        # Agent 通信总线（多实例审查，AGENT_BUS_ENABLED=False 时失效，见 future-plans.md）
        # 容错：导入失败不影响主功能
        self._bus = None
        self._poll_timer = None
        if AGENT_BUS_ENABLED:
            try:
                from tamias.agent_bus import AgentBus
                self._bus = AgentBus(self._pet_name if self._pro_mode else "栗栗")
                self._poll_timer = QTimer(self)
                self._poll_timer.timeout.connect(self._poll_reviews)
                if self._pro_mode:
                    self._poll_timer.start(3000)
            except Exception as e:
                print(f"[栗栗] Agent总线初始化失败: {e}")
                self._bus = None
                self._poll_timer = None
        # 排队面板：显示「正在处理 + 排队中」列表，让主人看明白消息为什么还没轮到，
        # 且能单独删掉排队中的某一条。队列数据本身就有了（回车入队 +
        # 干完自动接着做），这里补「可见性 + 上限 3 + 删除」三件事。
        self._queue_panel = QFrame()
        self._queue_panel.setStyleSheet(
            "QFrame { background: #F3EADB; border: 1px solid #DDCCAE; border-radius: 6px; }"
        )
        self._queue_layout = QVBoxLayout(self._queue_panel)
        self._queue_layout.setContentsMargins(8, 6, 8, 6)
        self._queue_layout.setSpacing(3)
        self._queue_panel.setVisible(False)
        main_layout.addWidget(self._queue_panel)

        main_layout.addLayout(input_layout)

        # 按模式初始化启动器/返回按钮的可见性（普通模式仅聊天）
        self._apply_launcher_mode()

    # ==================== 主题 ====================

    def _on_usage(self):
        """打开「使用说明」阅读对话框（新手指引，普通/专业模式都可点）。"""
        from tamias.usage_viewer import show_usage_guide
        show_usage_guide(parent=self)

    def _build_theme_switch(self):
        """专业模式主题切换：「主题风格」文字 + 两个小圆点（深色/暖棕），放启动器右上角。"""
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self._theme_label = QLabel(tr("主题风格"))
        self._theme_label.setFont(ui_font(11))
        self._theme_label.setStyleSheet("color:#888;")
        h.addWidget(self._theme_label)
        self._theme_dark_btn = QPushButton()
        self._theme_warm_btn = QPushButton()
        for b, tip in ((self._theme_dark_btn, tr("深色")), (self._theme_warm_btn, tr("暖棕"))):
            b.setFixedSize(18, 18)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
        self._theme_dark_btn.clicked.connect(lambda: self.set_theme("dark"))
        self._theme_warm_btn.clicked.connect(lambda: self.set_theme("warm"))
        h.addWidget(self._theme_dark_btn)
        h.addWidget(self._theme_warm_btn)
        self._refresh_theme_switch()
        return bar

    def _refresh_theme_switch(self):
        """刷新两个小圆点：当前主题的圆点加一圈描边（选中态）。"""
        if not hasattr(self, "_theme_dark_btn"):
            return
        dark = self._is_dark_theme()
        idle_bd = "#555" if dark else "#C7A27E"  # 未选中圈：深色灰 / 暖棕淡
        self._theme_dark_btn.setStyleSheet(
            f"QPushButton{{background:#1A1A1A;border:2px solid {'#A9745B' if self._pro_theme == 'dark' else idle_bd};border-radius:9px;}}")
        self._theme_warm_btn.setStyleSheet(
            f"QPushButton{{background:#A9745B;border:2px solid {'#463329' if self._pro_theme == 'warm' else idle_bd};border-radius:9px;}}")

    def _set_current_project(self, proj_id: str, folder: str):
        """统一切换当前项目：设项目 id + 工作目录 + 通知上层切换记忆/dsh cwd"""
        self._current_project = proj_id
        self._working_dir = folder
        self.set_working_dir(folder)
        if self._settings:
            self._settings.set("work_dir", folder)
        self.folder_opened.emit(folder)
        self._sync_conv_to_viewer()

    def _sync_conv_to_viewer(self):
        """把「当前项目」的对话列表 + 当前对话 id 推给右侧「对话」标签页。
        在切项目 / 切对话 / 新建 / 删除 / 重命名对话后调用，让标签页和实际列表保持一致。"""
        if not hasattr(self, "_viewer") or self._viewer is None:
            return
        convs = []
        proj_name = ""
        if self._is_project_store and self._conv_store:
            proj = self._conv_store.get_project(self._current_project or CHITCHAT_PROJECT_ID)
            if proj:
                convs = proj.list_conversations()
                proj_name = getattr(proj, "name", "") or ""
        cur = self._current_conv.id if self._current_conv is not None else ""
        self._viewer.set_conversations(convs, cur, proj_name)

    def _on_call(self):
        """摇人——弹出选择框"""
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("摇人"))
        dlg.setFixedSize(200, 180)
        dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        dlg.setStyleSheet("QDialog{background:#0D0D0D;border:1px solid #444;}QLabel{color:#CCC;font-size:13px;}QPushButton{background:#1A1A1A;color:#CCC;border:1px solid #444;border-radius:4px;padding:8px;}QPushButton:hover{background:#333;color:#0f0;}")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(tr("要增加几个人？")))
        for n in (1, 2, 3):
            btn = QPushButton(tr("增加{}人", n))
            def make_handler(count=n):
                return lambda: (self._do_call(count), dlg.accept())
            btn.clicked.connect(make_handler(n))
            layout.addWidget(btn)
        dlg.exec()

    def _do_call(self, count: int):
        """启动指定数量的新实例"""
        import subprocess, os, sys, tempfile

        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        lock = os.path.join(tempfile.gettempdir(), 'tamias', 'instance.pid')

        for _ in range(count):
            try:
                if os.path.exists(lock):
                    os.remove(lock)
            except Exception:
                pass
            subprocess.Popen(
                [sys.executable, '-m', 'tamias.main'],
                cwd=project_dir,
                creationflags=0x08000000 if sys.platform == 'win32' else 0,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        print(f"[栗栗] 已摇{count}人")

    # ==================== Agent 通信 ====================

    def _on_send_review(self):
        """发送审查任务给其他实例"""
        if not self._bus:
            self.add_message("ai", tr("Agent 总线未初始化，无法发送"))
            return
        task = self._input_edit.toPlainText().strip() or "请审查当前项目"
        plan = progress = issues = ""  # 计划/进度/问题面板已删，审查不再带这三项
        code = ""
        for m in reversed(self._messages):
            if m["role"] in ("ai", "plan"):
                code = m["content"][:2000]
                break
        ok = self._bus.send_review(task, plan, progress, issues, code)
        if ok:
            self.add_message("ai",
                tr("📤 审查请求已发送！\n\n"
                   "任务：{}\n"
                   "计划/进度/问题已打包\n\n"
                   "请打开另一个栗栗实例，\n它会自动收到审查请求。", task))
            # 按钮闪烁反馈
            self._send_review_btn.setStyleSheet(
                "QPushButton{background:#00AA44;color:#fff;border:1px solid #00AA44;border-radius:4px;padding:6px;}")
            QTimer.singleShot(2000, lambda: self._send_review_btn.setStyleSheet(
                "QPushButton{background:#1A1A1A;color:#888;border:1px solid #444;border-radius:4px;padding:6px;}QPushButton:hover{background:#333;color:#0f0;}"))
            print(f"[栗栗] 审查请求已发送: {task}")
        else:
            self.add_message("ai", tr("发送失败，请重试"))

    def _poll_reviews(self):
        """轮询检查是否有新审查请求"""
        if not self._bus: return
        data = self._bus.poll()
        if not data:
            return
        # 有新的审查请求 → 弹通知 + 激活审批栏
        from_name = data.get("from", tr("其他栗栗"))
        task_text = data.get("task", "")
        self.add_message("ai",
            tr("📨 收到审查请求！\n来自：{}\n任务：{}\n\n"
               "项目面板数据已自动填入，可直接开始审查", from_name, task_text))
        # 闪烁审批栏作为强提醒
        self._activate_approval(tr("审查请求：{}\n来自：{}", task_text, from_name))
        print(f"[栗栗] 收到审查请求: {task_text} from {from_name}")
        # 计划/进度/问题面板已删，只把审查内容贴进对话
        if data.get("code"):
            self.add_message("ai", tr("📋 审查内容：\n{}", data['code'][:1500]))

    def _on_attach(self):
        """上传文件/图片"""
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("选择文件"), "",
            tr("所有文件 (*.*);;图片 (*.png *.jpg *.jpeg *.gif *.bmp);;代码 (*.py *.js *.ts *.html *.css)")
        )
        if not files:
            return
        self._pending_files.extend(files)
        # 显示附件标签
        for f in files:
            name = os.path.basename(f)
            tag = QLabel(f"📎 {name}")
            tag.setFont(mono_font(9))
            tag.setStyleSheet("color: #888; background: #111; border:1px solid #333; border-radius:4px; padding:2px 6px;")
            tag.setToolTip(f)
            # 点击移除
            tag.mousePressEvent = lambda e, f=f, t=tag: self._remove_attachment(f, t)
            self._attachments_layout.insertWidget(
                self._attachments_layout.count(), tag)
            QTimer.singleShot(50, self._scroll_to_bottom)

    def _remove_attachment(self, file_path: str, tag_widget):
        """移除附件"""
        if file_path in self._pending_files:
            self._pending_files.remove(file_path)
        self._attachments_layout.removeWidget(tag_widget)
        tag_widget.deleteLater()

    def _on_new_conversation(self):
        """开启新对话"""
        self._current_conv = None
        self._messages.clear()
        self._rebuild_message_widgets()
        self._add_welcome_message()
        # 通知清会话，重新开始
        self.folder_opened.emit("__CLEAR_SESSION__")
        # 当前对话悬空，刷新「对话」标签页（当前项不高亮，等发第一条消息才新建对话）
        self._sync_conv_to_viewer()

    def _on_open_folder(self):
        """打开文件夹选择器"""
        folder = QFileDialog.getExistingDirectory(
            self, tr("选择工作目录"), "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if folder:
            # 盘符根不能当工作目录（同 open_project_folder，见 workspace.is_drive_root）
            if is_drive_root(folder):
                QMessageBox.warning(
                    self, tr("打不开文件夹"),
                    tr("不能把整个盘（如 C:\\）当工作目录，换一个普通文件夹试试～"))
                return
            self.set_working_dir(folder)
            self.folder_opened.emit(folder)

    def set_working_dir(self, path: str):
        """更新显示的工作目录"""
        self._working_dir = path
        self._dir_label.setText(f"{path}")
        self._dir_label.setVisible(self._pro_mode and bool(path))
        # 同步右侧查看器面板的文件树根 + 工作目录显示
        if hasattr(self, "_viewer"):
            self._viewer.set_work_dir(path)

    def _apply_launcher_mode(self):
        """按模式设置启动器入口 + 返回按钮的可见性。
        普通模式 = 仅聊天：隐藏「打开文件夹」和右侧欢迎区（去掉「欢迎回来」占位），
        只留「日常闲聊」「使用说明」入口，左侧占满；返回按钮始终显示（普通模式进去也要能出来）。
        专业模式 = 全功能：所有入口都显示，左侧限宽给右侧欢迎区留位置。"""
        is_pro = self._pro_mode
        # 项目入口：仅专业模式显示；「使用说明」两种模式都显示（新手指引常驻）
        self._btn_open.setVisible(is_pro)
        # 「日常闲聊」仅普通模式显示：闲聊由普通模式承接，专业模式专注「打开文件夹」干活，
        # 少一个入口、职责更清晰（专业模式打开文件夹后想闲聊，切回普通模式即可）
        self._btn_free.setVisible(not is_pro)
        # 主题切换（「主题风格」+ 圆点）：仅专业模式显示
        self._theme_switch_bar.setVisible(is_pro)
        # 右侧欢迎区（「欢迎回来」占位）：仅专业模式显示
        self._launcher_right.setVisible(is_pro)
        # 返回按钮：所有模式都显示
        self._back_btn.setVisible(True)
        # 布局：普通模式左侧占满（解除 380 限宽），专业模式左侧限宽给右侧留位置
        if is_pro:
            self._launcher_left.setMaximumWidth(380)
            self._launcher_layout.setStretch(0, 0)   # 左侧不拉伸，保持 380
            self._launcher_layout.setStretch(1, 1)   # 中间空隙撑开，把左/右顶到两边
        else:
            self._launcher_left.setMaximumWidth(16777215)  # 解除限宽，让左侧占满
            self._launcher_layout.setStretch(0, 1)   # 左侧拉伸占满
            self._launcher_layout.setStretch(1, 0)   # 中间空隙不占
        # 模式切换按钮：普通模式显示「专业模式」、专业模式显示「普通模式」（图标 + 文案随模式换）
        if is_pro:
            apply_icon(self._mode_btn, "message-circle", tr("普通模式"), size=14)
            self._mode_btn.setToolTip(tr("切回普通模式（仅聊天）"))
            # 对话页顶部栏的切换按钮同步成「普通」（点击同样走 mode_switch_requested）
            self._page_mode_btn.setText(tr("普通"))
            self._page_mode_btn.setToolTip(tr("切回普通模式（仅聊天）"))
        else:
            apply_icon(self._mode_btn, "zap", tr("专业模式"), size=14)
            self._mode_btn.setToolTip(tr("有正事要办？切到专业模式，让我来帮你办"))
            self._page_mode_btn.setText(tr("⚡专业"))
            self._page_mode_btn.setToolTip(tr("切到专业模式，让我来帮你办"))

    def _apply_launcher_theme(self):
        """按模式给启动器上色：普通模式用暖棕主题，专业模式保持深色终端风（不动）。
        启动器标题/按钮/最近列表的样式在这里按模式切换。"""
        if self._is_dark_theme():
            # 深色主题：终端风（保持原样）
            title_c, sub_c = "#CCC", "#888"
            btn_base = ("background:#1A1A1A;color:#CCC;border:1px solid #444;"
                        "border-radius:6px;padding:12px;font-family: 'HarmonyOS Sans SC';font-size:13px;"
                        "text-align:left;margin-left:{offset};")
            recent_label_c = "#666"
            recent_qss = ("QListWidget{background:#0D0D0D;border:1px solid #333;color:#CCC;font-size:11px;}"
                          "QListWidget::item{padding:6px;border-bottom:1px solid #222;}"
                          "QListWidget::item:hover{background:#1A1A1A;}")
        else:
            # 普通模式：暖棕侦探风（与聊天页暖棕主题协调）
            title_c, sub_c = "#7A5540", "#A98B6D"
            btn_base = ("background:#FFFDF7;color:#463329;border:1px solid #C7A27E;"
                        "border-radius:6px;padding:12px;font-family: 'HarmonyOS Sans SC';font-size:14px;"
                        "text-align:left;margin-left:{offset};")
            recent_label_c = "#A98B6D"
            recent_qss = ("QListWidget{background:#FFFDF7;border:1px solid #E4D3BC;color:#463329;font-size:12px;}"
                          "QListWidget::item{padding:6px;border-bottom:1px solid #F0E4D2;}"
                          "QListWidget::item:hover{background:#F5EDE1;}")

        self._launcher_title.setStyleSheet(f"color:{title_c};")
        self._launcher_sub.setStyleSheet(f"color:{sub_c};")
        self._recent_label.setStyleSheet(f"color:{recent_label_c};")
        self._recent_list.setStyleSheet(recent_qss)
        for btn in (self._btn_free, self._btn_open, self._btn_usage):
            btn._base_style = btn_base
            btn.setStyleSheet(btn_base.replace("{offset}", "0px"))
        # 模式切换按钮：次级小按钮，配色随主题（深色=终端灰，暖棕=侦探棕）
        if self._is_dark_theme():
            self._mode_btn.setStyleSheet(
                "QPushButton{background:transparent;color:#888;border:1px solid #444;"
                "border-radius:13px;padding:5px 14px;font-size:11px;}"
                "QPushButton:hover{background:#1A1A1A;color:#CCC;border-color:#666;}")
        else:
            self._mode_btn.setStyleSheet(
                "QPushButton{background:transparent;color:#A9745B;border:1px solid #C7A27E;"
                "border-radius:13px;padding:5px 14px;font-size:11px;}"
                "QPushButton:hover{background:#F5EDE1;color:#7A5540;border-color:#A9745B;}")

    def _is_dark_theme(self) -> bool:
        """当前是否用深色主题：专业模式且选「黑」才是深色；普通模式永远暖棕。"""
        return self._pro_mode and IS_DARK.get(self._pro_theme, False)

    def _menu_style(self) -> str:
        """右键菜单统一配色，随主题切。深色 = 现状终端黑；暖棕 = 米白底 + 深咖字
        （桌宠右键菜单同款，对比度约 8:1，清晰不糊）。历史/最近/…菜单共用，避免散落硬编码。"""
        if self._is_dark_theme():
            return """
            QMenu { background-color: #1A1A1A; color: #CCC; border: 1px solid #444; border-radius: 6px; padding: 5px; }
            QMenu::item { padding: 8px 24px 8px 14px; border-radius: 4px; font-size: 13px; }
            QMenu::item:selected { background-color: #333; color: #FFF; }
            QMenu::separator { height: 1px; background: #333; margin: 4px 8px; }
            """
        return """
            QMenu { background-color: #F5EDE1; color: #463329; border: 1px solid #C7A27E; border-radius: 6px; padding: 5px; }
            QMenu::item { padding: 8px 24px 8px 14px; border-radius: 4px; font-size: 13px; }
            QMenu::item:selected { background-color: #EDE0CC; color: #463329; }
            QMenu::separator { height: 1px; background: #E4D3BC; margin: 4px 8px; }
            """

    def _is_terminal(self) -> bool:
        """当前是否用「终端块」消息结构：专业模式一律终端块（无气泡框），普通模式气泡框。
        深色/暖棕两种主题结构一致，只有字色不同（颜色仍看 _is_dark_theme）。"""
        return self._pro_mode

    def _chat_font_size(self) -> int:
        """聊天气泡正文字号（普通模式实际值，专业模式 = 该值 - 3）。"""
        if self._settings is not None:
            try:
                return max(10, min(20, int(self._settings.chat_font_size)))
            except (TypeError, ValueError):
                pass
        return 13

    def set_chat_font_size(self, size: int):
        """调整聊天气泡正文字号（普通=该值，专业=该值-3），存配置并重建气泡。
        设置面板的字号滑块松手时调用；拖动过程中只改数字，不触发这里。"""
        size = max(10, min(20, int(size)))
        if self._settings is not None:
            self._settings.chat_font_size = size
        self._rebuild_message_widgets()

    def set_theme(self, name: str):
        """切换专业模式主题（dark=深色现状 / warm=暖棕），刷新配色 + 气泡 + 按钮高亮。"""
        if name not in PRO_THEME_ORDER:
            return
        self._pro_theme = name
        if self._settings is not None:
            self._settings.set("pro_theme", name)  # 持久化到 config.yaml：重启后记住
        self._apply_theme()
        self._rebuild_message_widgets()
        self._refresh_theme_switch()

    def _on_toggle_panel(self):
        """「隐藏/显示预览面板」：收起/展开右侧查看器（只影响专业模式）。
        眼睛划掉 = 已收起（点一下展开），眼睛 = 已展开（点一下收起）。"""
        self._viewer_hidden = not self._viewer_hidden
        self._viewer.setVisible(not self._viewer_hidden)
        # 展开查看器时同样会遇到「隐藏→显示记 0 宽」的问题（QSplitter 不恢复隐藏子项宽度），
        # 展开后重新按默认比例分配一次，否则面板看不见。
        if not self._viewer_hidden:
            self._content_area.setSizes([820, 540])
        # 换图标 + 提示：收起后图标变「眼睛」（提示可点开），展开时变「眼睛划掉」（提示可收起）
        apply_icon(self._panel_btn, "eye" if self._viewer_hidden else "eye-off", tr("👁"), size=16)
        self._panel_btn.setToolTip(tr("显示预览面板") if self._viewer_hidden else tr("隐藏预览面板"))

    def set_pro_mode(self, enabled: bool):
        changed = (enabled != self._pro_mode)  # 模式是否真的变了（防止重复触发时误切回启动器）
        self._pro_mode = enabled
        w = DIALOG_WIDTH_PRO if enabled else DIALOG_WIDTH
        h = DIALOG_HEIGHT_PRO if enabled else DIALOG_HEIGHT
        self.resize(w, h)
        self._apply_theme()
        self._apply_launcher_mode()  # 同步启动器入口 + 返回按钮（普通模式仅聊天）
        self._viewer.setVisible(enabled and not self._viewer_hidden)
        # 查看器面板从「隐藏→显示」时，QSplitter 会把它记成 0 宽（普通模式 setSizes 时它隐藏），
        # 导致切专业模式后查看器看不见、分隔条也拉不宽。这里显示后重新按默认比例分配一次。
        if enabled and not self._viewer_hidden:
            self._content_area.setSizes([820, 540])
        self._panel_btn.setVisible(enabled)  # 预览面板开关只在专业模式出现
        self._call_btn.setVisible(enabled)
        self._new_conv_btn.setVisible(True)  # 新对话按钮所有模式都显示
        self._history_btn.setVisible(True)  # 历史按钮所有模式都显示（跟新对话配对）
        self._attach_btn.setVisible(enabled)
        self._prompt_btn.setVisible(enabled)
        # 启动/停止轮询（AGENT_BUS_ENABLED=False 时 _poll_timer 为 None）
        if self._poll_timer is not None:
            if enabled:
                self._poll_timer.start(3000)
            else:
                self._poll_timer.stop()
        self._folder_btn.setVisible(enabled)
        self._dir_label.setVisible(enabled and bool(self._working_dir))
        self._rebuild_message_widgets()
        # 切换模式时回到「该模式的初始界面（启动器）」，别停在当前对话里——
        # 否则普通模式聊到一半切专业模式，会留在当前对话、只是换个皮肤（用户报的 bug）。
        # 同时把对话页状态一并清干净：先落盘当前对话，再置空 _current_conv/_messages，
        # 让「切模式」这个动作本身就和旧对话彻底断开，不靠后续入口清空的巧合兜底。
        if changed:
            self._sync_conv()
            self._current_conv = None
            self._messages.clear()
            self._rebuild_message_widgets()
            self._slide_to(0)
        # 切到专业模式时刷新一次引擎连接状态灯（状态可能已变）
        if enabled:
            QTimer.singleShot(0, self._viewer.refresh_engine_status)

    def _apply_theme(self):
        if self._is_dark_theme():
            bg = "#0D0D0D"
            border = "#333333"
            inp_bg = "#0D0D0D"
            inp_c = "#00FF66"
            inp_bo = "#00FF66"
            sc_bg = "#0D0D0D"
            sc_bo = "#333333"
            tc = "#00FF66"
            self._title_label.setStyleSheet(f"color:{tc}; padding:5px; font-family: 'JetBrains Mono';")
            # 状态文字：淡一点的绿，不抢标题「栗栗」的视觉
            self._status_label.setStyleSheet(f"color:{tc}; opacity:0.75; font-family: 'JetBrains Mono';")
            self._send_btn.setStyleSheet(
                f"background:#1A1A1A; color:{tc}; border:1px solid {tc}; "
                f"border-radius:4px; font-family: 'JetBrains Mono';")
            self._send_btn_norm = self._send_btn.styleSheet()
            self._send_btn_wait = (
                f"background:#FF9800; color:#0D0D0D; border:1px solid #FF9800; "
                f"border-radius:4px; font-family: 'JetBrains Mono';")
            self._input_edit.setFont(mono_font(10))
            self._input_edit.setStyleSheet(
                f"background:{inp_bg}; color:{inp_c}; border:1px solid {inp_bo}; "
                f"border-radius:0; padding:8px; font-family: 'JetBrains Mono';"
                f"selection-background-color:#333333; selection-color:{inp_c};")
            self._input_edit_focus_extra = ""
        else:
            bg = COLOR_BG
            border = "#C7A27E"            # 浅暖棕边框
            inp_bg = COLOR_INPUT_BG
            inp_c = "#463329"             # 深咖文字
            inp_bo = "#C7A27E"            # 输入框边框浅暖棕
            sc_bg = "#F5EDE1"             # 滚动区融入暖米白背景
            sc_bo = "#E4D3BC"             # 滚动区边框浅暖棕
            tc = "#7A5540"                # 标题暖棕
            self._title_label.setStyleSheet(f"color:{tc}; padding:5px;")
            # 状态文字：浅一点的暖棕，不抢标题「栗栗」的视觉
            self._status_label.setStyleSheet(f"color:#B07B50; opacity:0.85;")
            # 元信息（⏱ 秒表 · token）挂在气泡右侧，不占标题栏
            self._send_btn.setStyleSheet(
                f"background:{COLOR_SEND_BTN}; color:white; border:none; border-radius:8px;")
            self._send_btn_norm = self._send_btn.styleSheet()
            self._send_btn_wait = (
                f"background:#FF9800; color:white; border:none; border-radius:8px;")
            self._input_edit.setFont(ui_font(13))
            self._input_edit.setStyleSheet(
                f"background:{inp_bg}; color:{inp_c}; border:2px solid {inp_bo}; "
                f"border-radius:8px; padding:8px;"
                f"selection-background-color:#EDE0CC; selection-color:{inp_c};")
            self._input_edit_focus_extra = f"border-color:#A9745B; color:{inp_c};"

        self.setStyleSheet(f"QDialog {{ background:{bg}; border:2px solid {border}; border-radius:0; }}")
        self._scroll_area.setStyleSheet(
            f"QScrollArea {{ background:{sc_bg}; border:1px solid {sc_bo}; border-radius:0; }}"
            f"QScrollArea > QWidget > QWidget {{ background:{sc_bg}; }}"
            f"QScrollBar:vertical {{ width:6px; background:#1A1A1A; }}"
            f"QScrollBar::handle:vertical {{ background:#444; border-radius:0; }}")
        self._msg_container.setStyleSheet(f"background:{sc_bg};")
        # 输入框 focus 样式单独设
        focus_border = inp_c if self._is_dark_theme() else "#A9745B"
        self._input_edit.setStyleSheet(
            self._input_edit.styleSheet() +
            f"QTextEdit:focus {{ border-color:{focus_border}; color:{inp_c}; }}")
        # 启动器首页配色跟着主题走（普通模式暖棕，专业模式深色不动）
        self._apply_launcher_theme()
        # 侧边栏/审批栏/项目面板/欢迎区的散落深色，也随主题切
        self._apply_panel_theme()

    def _apply_panel_theme(self):
        """侧边栏/审批栏/项目面板/欢迎区这些「散落深色硬编码」集中到这里，随主题切。
        深色 = 现状终端风；暖棕 = 栗栗侦探风（米白底 + 深咖字 + 暖棕描边）。"""
        dark = self._is_dark_theme()
        if dark:
            panel = "#111"; deep = "#0D0D0D"; border = "#333"; border2 = "#444"
            text = "#CCC"; dim = "#888"; faint = "#555"; itext = "#AAA"; btn = "#1A1A1A"
            hover = "#222"; sel = "#333"; scroll_h = "#555"; item_bd = "#222"
            accent = "#0f0"; list_font = "'JetBrains Mono'"
            right_bg = "#0A0A0A"; right_bd = "#222"; welcome_c = "#333"; hint_c = "#2A2A2A"
        else:
            panel = "#FFFDF7"; deep = "#FFFFFF"; border = "#E4D3BC"; border2 = "#C7A27E"
            text = "#463329"; dim = "#7A5540"; faint = "#A98B6D"; itext = "#463329"; btn = "#FFFDF7"
            hover = "#F5EDE1"; sel = "#E4D3BC"; scroll_h = "#C7A27E"; item_bd = "#F0E4D2"
            accent = "#A9745B"; list_font = "'HarmonyOS Sans SC'"
            right_bg = "#F5EDE1"; right_bd = "#E4D3BC"; welcome_c = "#7A5540"; hint_c = "#A98B6D"

        # 右侧查看器面板配色随主题走
        if hasattr(self, "_viewer"):
            self._viewer.apply_theme(dark)

        # 欢迎区 + 返回按钮
        self._launcher_right.setStyleSheet(f"background:{right_bg}; border-left:1px solid {right_bd};")
        self._welcome_lb.setStyleSheet(f"color:{welcome_c};")
        self._hint_lb.setStyleSheet(f"color:{hint_c};")
        self._theme_label.setStyleSheet(f"color:{dim};")
        self._back_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{dim};border:1px solid {border2};border-radius:3px;}}QPushButton:hover{{color:{text};}}")

    # ==================== 事件过滤 ====================

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            # 输入框 Enter → 发送
            if obj is self._input_edit:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                        self._on_input_enter()
                        return True
            # 按住 Alt 键 = 说话（push-to-talk 快捷键，跟「按住语音按钮」等效）
            # 不 return True：让 Alt 继续传下去，避免破坏 Alt+Tab / Alt+F4 等组合键
            if key == Qt.Key.Key_Alt and not event.isAutoRepeat():
                self._on_speech_press()
            # 全局 1=批准 2=拒绝（有内联审批卡片在才生效）
            if key == Qt.Key.Key_1 and self._approval_approve_btn is not None:
                self._on_plan_approved(True)
                return True
            if key == Qt.Key.Key_2 and self._approval_reject_btn is not None:
                self._on_plan_approved(False)
                return True
            # 全局 Esc = 终止（忙时有活才生效，显式打断当前任务；闲时 Esc 走 QDialog 默认）
            if key == Qt.Key.Key_Escape and self._waiting:
                self._on_cancel()
                return True
        elif event.type() == QEvent.Type.KeyRelease:
            # 松开 Alt = 停止说话
            if event.key() == Qt.Key.Key_Alt and not event.isAutoRepeat():
                self._on_speech_release()
        return super().eventFilter(obj, event)

    # ==================== 语音输入 ====================

    def _on_speech_press(self):
        """按住（语音按钮或 Alt 键）：开始识别。"""
        self._speech.start()

    def _on_speech_release(self):
        """松手：停止识别，结果经 text_ready 信号回到 _on_speech_text。"""
        self._speech.stop()

    def _on_speech_text(self, text):
        """语音转出的文字 → 追加进输入框（已有字则补个空格防粘连）。"""
        if not text:
            return
        cur = self._input_edit.toPlainText()
        if cur and not cur.endswith((" ", "\n")):
            text = " " + text
        self._input_edit.insertPlainText(text)
        self._input_edit.setFocus()

    def _on_speech_error(self, msg):
        """语音识别出错 → 状态栏 + 气泡短暂提示，几秒后自动清掉。
        不能像「正在思考」那样一直挂着——错误是「一次性事件」，不主动清的话
        气泡会永久卡在这句话上（测试员报的 bug）。"""
        self._set_status(msg)
        QTimer.singleShot(4000, lambda: self._clear_speech_error(msg))

    def _clear_speech_error(self, msg):
        """定时清掉语音错误提示；只清「还是这条」的状态，别误清期间新出现的
        「正在思考」等正常状态。"""
        if self._status_label.text() == msg:
            self._set_status("")

    # ==================== 提示词库 ====================

    def _open_prompt_library(self):
        """打开提示词库弹窗；选中词条 → 追加填入输入框（不自动发送）。"""
        if not self._pro_mode:
            return  # 提示词库只在专业模式提供（按钮不显示，Ctrl+P 也一并失效）
        from tamias.prompt_library import PromptLibraryDialog
        dlg = PromptLibraryDialog(settings=self._settings, parent=self)
        dlg.picked.connect(self._on_prompt_picked)
        dlg.exec()

    def _on_prompt_picked(self, text):
        """提示词被选中：追加到输入框末尾（已有字则前补空格防粘连），不覆盖已有文字。
        跟语音不同——语音是边说边打、光标天然在末尾；提示词是「点选」动作，光标可能
        停在输入框中间（用户编辑到一半），必须显式移到末尾再插，否则会把已有半句话截断。"""
        cur = self._input_edit.toPlainText()
        if cur and not cur.endswith((" ", "\n")):
            text = " " + text
        self._input_edit.moveCursor(QTextCursor.MoveOperation.End)
        self._input_edit.insertPlainText(text)
        self._input_edit.setFocus()

    # ==================== 发送逻辑 ====================

    def _on_send_clicked(self):
        # 按钮：忙时 = 终止（显式打断），闲时 = 发送
        if self._waiting:
            self._on_cancel()
        else:
            self._on_send()

    def _on_input_enter(self):
        """输入框回车：忙时 = 入队（不打断当前任务），闲时 = 直接发送。
        跟按钮分开——按钮忙时是「终止」，回车忙时是「排队」（学 Claude Code：
        运行中接话是排队，不是抢占，也不是丢弃）。"""
        if self._waiting:
            self._enqueue_pending()
        else:
            self._on_send()

    def _enqueue_pending(self):
        """忙时按回车：把输入框的话（含附件）排进队列，当前任务干完自动接着做。"""
        text = self._input_edit.toPlainText().strip()
        if not text:
            return  # 忙时按空回车：啥也不做
        # 排队上限：满了不吞消息、也不清输入框，让主人等干完再发
        if len(self._pending_queue) >= MAX_PENDING_QUEUE:
            self._set_status(tr("排队满了（最多 {} 个），等干完这条再发～", MAX_PENDING_QUEUE))
            return
        # 附件跟文本一起打包（同 _on_send 的 __FILES__ 前缀），队列只存一条完整消息
        if self._pending_files:
            text = f"__FILES__{';'.join(self._pending_files)}__MSG__{text}"
            self._pending_files.clear()
            while self._attachments_layout.count() > 0:
                w = self._attachments_layout.takeAt(0)
                if w.widget():
                    w.widget().deleteLater()
        self._pending_queue.append(text)
        self._input_edit.clear()
        self._refresh_queue_panel()  # 面板实时显示队列（替代旧的「已排队 N 条」状态文案）

    @staticmethod
    def _queue_display_text(text: str) -> str:
        """从（可能带 __FILES__ 附件前缀的）消息里摘出给队列面板显示的用户原话，超长截断。"""
        if "__MSG__" in text:
            text = text.split("__MSG__", 1)[1]
        text = text.strip()
        return text if len(text) <= QUEUE_TEXT_MAX else text[:QUEUE_TEXT_MAX] + "…"

    def _refresh_queue_panel(self):
        """重画排队面板：一行「正在处理」+ 若干「排队中（可删）」，空则整块隐藏。
        队列数据 _pending_queue / _current_task_text 只在 UI 线程读写，无需加锁。"""
        while self._queue_layout.count():
            item = self._queue_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not self._failed_task and not self._current_task_text and not self._pending_queue:
            self._queue_panel.setVisible(False)
            return
        self._queue_panel.setVisible(True)
        # 失败停住行（红色，带「重试」+「放弃」✕）：排最上，处置后才恢复排队
        if self._failed_task:
            self._queue_layout.addWidget(self._make_failed_row(self._failed_task))
        # 处理中行（不可删：删除靠主按钮「终止」）
        if self._current_task_text:
            self._queue_layout.addWidget(self._make_queue_row(
                f"{self._queue_display_text(self._current_task_text)}（{tr('处理中')}）",
                deletable=False))
        # 排队行（可删）
        for i, t in enumerate(self._pending_queue):
            self._queue_layout.addWidget(self._make_queue_row(
                f"{self._queue_display_text(t)}（{tr('排队中')}）",
                deletable=True, queue_index=i))

    def _make_queue_row(self, label: str, deletable: bool, queue_index: int = -1) -> QWidget:
        """做一行队列条目：文字 +（可选）✕ 删除按钮。"""
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        lb = QLabel(label)
        lb.setFont(ui_font(9))
        lb.setStyleSheet("color:#7A5540;")
        hl.addWidget(lb, stretch=1)
        if deletable:
            btn = QPushButton("✕")
            btn.setFixedSize(16, 16)
            btn.setFont(ui_font(9))
            btn.setToolTip(tr("删掉这条排队"))
            btn.setStyleSheet(
                "QPushButton { background: transparent; color: #A9745B; border: none; }"
                "QPushButton:hover { color: #D9534F; }"
            )
            # 用默认参数捕获 queue_index，避免闭包晚绑定全部指向最后一条
            btn.clicked.connect(lambda _checked=False, i=queue_index: self._remove_queued(i))
            hl.addWidget(btn)
        return row

    def _remove_queued(self, index: int):
        """删掉排队中的第 index 条（点 ✕）。"""
        if 0 <= index < len(self._pending_queue):
            self._pending_queue.pop(index)
            self._refresh_queue_panel()

    def _make_failed_row(self, text: str) -> QWidget:
        """失败停住行：原话（处理失败，红色）+「重试」按钮 + ✕ 放弃按钮。"""
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        lb = QLabel(f"{self._queue_display_text(text)}（{tr('处理失败')}）")
        lb.setFont(ui_font(9))
        lb.setStyleSheet("color:#C0392B;")  # 失败用红色，区别于排队/处理的棕色
        hl.addWidget(lb, stretch=1)
        # 「重试」按钮：原样重发这条（复用原气泡，不再出一条「用户」气泡）
        retry = QPushButton(tr("重试"))
        retry.setFixedSize(34, 18)
        retry.setFont(ui_font(9))
        retry.setToolTip(tr("重发这条"))
        retry.setStyleSheet(
            "QPushButton { background: transparent; color: #C0392B; border: 1px solid #C0392B; border-radius: 3px; }"
            "QPushButton:hover { background: #C0392B; color: #fff; }"
        )
        retry.clicked.connect(self._retry_failed)
        hl.addWidget(retry)
        # ✕ 放弃按钮：放弃这条失败，若有排队则继续跑下一条
        dismiss = QPushButton("✕")
        dismiss.setFixedSize(16, 16)
        dismiss.setFont(ui_font(9))
        dismiss.setToolTip(tr("放弃这条，继续排队"))
        dismiss.setStyleSheet(
            "QPushButton { background: transparent; color: #A9745B; border: none; }"
            "QPushButton:hover { color: #D9534F; }"
        )
        dismiss.clicked.connect(self._dismiss_failed)
        hl.addWidget(dismiss)
        return row

    def _retry_failed(self):
        """重试失败停住的那条：原样重发（复用原气泡，不重复出「用户」行）。"""
        text = self._failed_task
        if not text:
            return
        # _send_text 开头会清 _failed_task；这里直接重发完整消息（含附件前缀）
        self._send_text(text, skip_add_user=True)

    def _dismiss_failed(self):
        """放弃失败停住的那条：撤下失败行，若有排队则自动继续跑下一条。"""
        self._failed_task = ""
        self._refresh_queue_panel()
        # 恢复排队：取出下一条接着做（和成功后的 drain 一致）
        if self._pending_queue:
            nxt = self._pending_queue.pop(0)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda t=nxt: self._send_text(t))

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()
        # 真正打断 dsh 干活线程：只取消 ReplyWorker 不够，run() 还在后台阻塞，
        # 这里额外置取消信号让 run() 的可中断等待提前返回。
        if self._on_cancel_work is not None:
            try:
                self._on_cancel_work()
            except Exception:
                pass  # 取消回调出错不影响 UI 收尾
        # 终止时若正卡在「审批等待」：收掉审批卡 + 释放审批事件（置「拒绝」），
        # 让 dsh 事件流线程从 value.wait() 解阻塞、回「拒绝」答案。否则事件流线程
        # 永远卡住 → 下一次干活的帧读不进来 → 新任务冻死。
        self._deactivate_approval()
        if self._gate_event is not None:
            self._gate_approved = False
            self._gate_event.set()
            self._gate_event = None
        # 反问卡同理：终止时收掉 + 释放反问事件（空答案 = 跳过），别留孤儿卡冻住事件流。
        self._hide_question_card()
        if self._gate_question_event is not None:
            self._gate_question_answers = []
            self._gate_question_event.set()
            self._gate_question_event = None
        self._waiting = False
        self._pending_queue.clear()  # 终止 = 重来，排队的一起清掉
        self._current_task_text = ""  # 终止后队列面板清空（正在处理 + 排队都消失）
        self._failed_task = ""  # 失败停住态也一并清掉
        self._refresh_queue_panel()
        self._stream_waiting = False  # 停止流式等待
        self._stream_idx = -1  # 终止后忽略后续流式增量
        self._set_status("")  # 隐藏标题栏状态
        self._stop_elapsed()  # 停秒表 + 隐藏 token 计数
        self._send_btn.setText(tr("发送"))
        self._send_btn.setStyleSheet(self._send_btn_norm)
        if 0 <= self._thinking_idx < len(self._messages):
            # 保留已经流式输出的文字，只在末尾追加「已取消」标记，别整段覆盖。
            # 之前这里直接覆盖 content，栗栗打了一半的字全没了——Claude Code 的
            # 体验是「停住、保留已输出内容」，不是「抹掉」，这里对齐。
            existing = self._messages[self._thinking_idx]["content"]
            if existing.strip():
                self._messages[self._thinking_idx]["content"] = existing + "\n\n" + tr("（已取消）")
            else:
                self._messages[self._thinking_idx]["content"] = tr("已取消～ (◕‿◕)")
            self._rebuild_message_widgets()
            # 取消也落盘：流式开始时空 AI 气泡（add_message("ai","")）已同步存成空，
            # 这里把「已取消」标记存进去，别让切回对话时看到一条空回复。
            self._sync_conv()
        self._thinking_idx = -1

    def _on_send(self):
        text = self._input_edit.toPlainText().strip()
        if not text:
            return
        self._input_edit.clear()
        self._input_edit.setFocus()
        self._send_text(text)

    def _send_text(self, text: str, skip_add_user: bool = False):
        """真正发一条消息（来自输入框或排队队列）。text 已 strip，可能带 __FILES__ 附件前缀。
        skip_add_user=True 复用已有气泡（重试失败条不重复出一条「用户」气泡）。"""
        # 无论发新消息还是重试失败条，都解除「失败停住」态（旧失败条已被处置）
        self._failed_task = ""
        if not skip_add_user:
            self.add_message("user", text)

        if self._on_message_callback:
            self._waiting = True
            self._send_btn.setText(tr("终止"))
            self._send_btn.setStyleSheet(self._send_btn_wait)
            self._current_task_text = text  # 队列面板「正在处理」行显示
            self._refresh_queue_panel()

            # 打包附件路径
            if self._pending_files:
                text = f"__FILES__{';'.join(self._pending_files)}__MSG__{text}"
                # 清空附件
                self._pending_files.clear()
                while self._attachments_layout.count() > 0:
                    w = self._attachments_layout.takeAt(0)
                    if w.widget(): w.widget().deleteLater()
            # 存完整消息（含附件前缀），失败停住时「重试」能原样重发；面板显示靠 _queue_display_text 摘纯文本
            self._current_task_text = text

            # dsh 时代：任务/聊天不再在 UI 层分开路由，统一交给 main.py
            # （gate 分类 → 闲聊走 DeepSeek / 干活走 Harness，审批由 Harness 自己的门禁弹窗）
            # 旧的 plan→审批两段式（_start_pro_mode_flow）已停用，代码保留备查。
            # 不再塞「请稍等」占位气泡：状态移到标题栏「栗栗」右边，
            # 气泡延迟到第一个流式文字增量到达时才创建（对话里干净）。
            self._thinking_idx = -1
            self._stream_idx = -1
            self._stream_buffer = ""
            self._stream_started = False
            self._stream_waiting = True
            self._step_list = None  # 新一轮开始：旧过程列表留在历史，新的干活再建新的
            self._plan_card = None  # 新一轮开始：旧计划卡留在历史，新的干活再建新的
            self._task_tokens = 0   # 新一轮开始：token 累计清零
            self._set_status(tr("正在思考…"))  # 标题栏先亮一句，等底层回传更具体状态
            self._start_elapsed()  # 起表：从这一刻开始实时计时 + token 计数，让用户看到没死机
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            # 带最近上下文，不污染角色
            recent = [m for m in self._messages[-6:] if m["role"] in ("user","ai","plan")]
            ctx = "\n".join(f"{'用户' if m['role']=='user' else '栗栗'}：{m['content'][:150]}" for m in recent)
            chat_text = f"以下是刚才的对话，请记住上下文：\n{ctx}\n---\n{text}" if ctx else text
            # 当前对话 id 传给 dsh 层做 session 记忆隔离（每个对话一份干活上下文）。
            # add_message（上方）已保证 _current_conv 非 None（悬空时新建 Conversation），
            # 重试失败条（skip_add_user=True）时 _current_conv 也已存在，读出的 id 正确。
            conv_id = self._current_conv.id if self._current_conv is not None else ""
            self._worker = ReplyWorker(self._on_message_callback, chat_text, self, conv_id=conv_id,
                                        on_chunk=self.stream_text.emit,
                                        on_status=self.status_text.emit,
                                        on_step=self.step_event.emit,
                                        on_todo=self.todo_event.emit,
                                        on_usage=self.usage_event.emit)
            self._worker.finished.connect(
                lambda reply: self._on_reply_done(self._thinking_idx, reply, ok=True))
            self._worker.failed.connect(
                lambda reply: self._on_reply_done(self._thinking_idx, reply, ok=False))
            self._worker.start()
        else:
            self.add_message("ai",
                tr("收到你的消息啦！你说：{}\n\n（请在设置中配置 DeepSeek API Key）", text))

    def request_gate_approval(self, description: str, detail: str = ""):
        """门禁审批：在聊天流底部插一张内联审批卡片，返回可阻塞等待的 threading.Event。
        调用方（后台线程）拿 Event 后 wait()；用户点批准/拒绝后 Event 被 set，
        结果存 self._gate_approved。普通模式、专业模式都用内联卡片，不弹独立窗、
        不占常驻右侧栏（学 Claude Code：审批内联出现在对话现场，答完即消失）。
        detail 是「具体操作」的原始命令/JSON，默认折叠、点开才看；传空则不显示该行。
        """
        import threading
        self._gate_event = threading.Event()
        self._gate_approved = False
        self._activate_approval(description, detail)
        return self._gate_event

    def _activate_approval(self, plan_text: str, detail: str = ""):
        """在聊天流底部插一张内联审批卡片（标题 + 操作详情 + 批准/拒绝按钮）。
        只在引擎真要审批时才出现，答完立刻消失——不再像旧版常驻右侧栏那样空占一列。
        detail 为「具体操作」的原始命令/JSON，默认折叠（点开才看），传空不显示。"""
        self._hide_approval_card()  # 理论上一次只有一张，先清旧的再插新的
        dark = self._is_dark_theme()
        if dark:
            card_bg = "#111"; border = "#333"; title_c = "#00DDDD"
            text_c = "#CCC"; ap = "#00AA44"; ap_h = "#00CC55"; rj_h = "#333"
        else:
            card_bg = "#FFFDF7"; border = "#C7A27E"; title_c = "#A9745B"
            text_c = "#463329"; ap = "#A9745B"; ap_h = "#8A5F49"; rj_h = "#E4D3BC"

        card = QWidget()
        card.setStyleSheet(f"QWidget{{background:{card_bg};border:1px solid {border};border-radius:6px;}}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel(strip_leading_emoji(tr("🔔 请求批准")))
        title.setFont(ui_font(11, bold=True))
        title.setStyleSheet(f"color:{title_c}; border:none; background:transparent;")
        lay.addWidget(title)

        desc = QLabel(plan_text[:600])
        desc.setWordWrap(True)
        desc.setFont(ui_font(11))
        desc.setStyleSheet(f"color:{text_c}; border:none; background:transparent;")
        desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(desc)

        # 「具体操作」原始命令/JSON：默认折叠，点开才看（普通用户一眼只看到人话）
        if detail:
            toggle = QPushButton(tr("▸ 具体操作（点开看）"))
            toggle.setCheckable(True)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setFont(ui_font(10))
            toggle.setStyleSheet(
                f"QPushButton{{background:transparent;color:{title_c};border:none;"
                f"text-align:left;padding:0;}}"
            )
            detail_lb = QLabel(detail[:2000])
            detail_lb.setWordWrap(True)
            detail_lb.setFont(mono_font(9))
            detail_lb.setStyleSheet(f"color:{text_c}; border:none; background:transparent;")
            detail_lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail_lb.hide()

            def _toggle_detail(checked: bool):
                detail_lb.setVisible(checked)
                toggle.setText(tr("▾ 具体操作（收起）") if checked else tr("▸ 具体操作（点开看）"))

            toggle.toggled.connect(_toggle_detail)
            lay.addWidget(toggle)
            lay.addWidget(detail_lb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        approve = apply_icon(QPushButton(), "circle-check", tr("✅ 批准（按 1）"))
        approve.setCursor(Qt.CursorShape.PointingHandCursor)
        approve.setFont(ui_font(11, bold=True))
        approve.setStyleSheet(f"QPushButton{{background:{ap};color:#fff;border:none;border-radius:4px;padding:8px 16px;}}QPushButton:hover{{background:{ap_h};}}")
        approve.clicked.connect(lambda: self._on_plan_approved(True))
        btn_row.addWidget(approve)

        reject = apply_icon(QPushButton(), "circle-x", tr("❌ 拒绝（按 2）"))
        reject.setCursor(Qt.CursorShape.PointingHandCursor)
        reject.setFont(ui_font(11, bold=True))
        reject.setStyleSheet(f"QPushButton{{background:transparent;color:{text_c};border:1px solid {border};border-radius:4px;padding:8px 16px;}}QPushButton:hover{{background:{rj_h};}}")
        reject.clicked.connect(lambda: self._on_plan_approved(False))
        btn_row.addWidget(reject)
        btn_row.addStretch()

        lay.addLayout(btn_row)

        self._msg_layout.insertWidget(self._msg_layout.count() - 1, card,
                                      alignment=Qt.AlignmentFlag.AlignLeft)
        self._approval_card = card
        self._approval_approve_btn = approve
        self._approval_reject_btn = reject
        # 延迟滚底：insertWidget 后要等下一个事件循环完成布局，滚动条最大值才会更新，
        # 同步滚会拿到旧的最大值、滚不到真正底部（审批卡被顶到屏幕外，用户要手动下拉）。
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _deactivate_approval(self):
        """摘掉内联审批卡片（批准/拒绝后调用；保留旧方法名给 _on_plan_approved 用）。"""
        self._hide_approval_card()

    def _hide_approval_card(self):
        """从消息流移除内联审批卡片并清引用（幂等，可反复调用）。"""
        card = self._approval_card
        self._approval_card = None
        self._approval_approve_btn = None
        self._approval_reject_btn = None
        if card is not None:
            try:
                self._msg_layout.removeWidget(card)
                card.deleteLater()
            except Exception:
                pass

    # ---------- 内联反问卡（dsh 反问主人做选择题，答完即删，不弹独立窗） ----------

    def request_gate_question(self, questions: list):
        """引擎反问主人时，在聊天流底部插一张内联反问卡，返回可阻塞等待的 threading.Event。
        调用方（后台线程）拿 Event 后 wait()；用户点「就这个啦/跳过」后 Event 被 set，
        答案存 self._gate_question_answers。普通/专业模式都用内联卡，不弹独立窗
        （学审批卡：反问也内联出现在对话现场，答完即消失）。"""
        import threading
        self._gate_question_event = threading.Event()
        self._gate_question_answers = []
        self._activate_question(questions)
        return self._gate_question_event

    def _activate_question(self, questions: list):
        """在聊天流底部插一张内联反问卡：标题 + 逐题（选项/自由输入）+ 就这个啦/跳过。
        只回答时出现、答完立刻消失——跟审批卡同套路，不弹独立 QDialog。"""
        self._hide_question_card()
        dark = self._is_dark_theme()
        if dark:
            c = {"card_bg": "#111", "border": "#333", "title_c": "#00DDDD", "text_c": "#CCC",
                 "panel": "#1A1A1A", "panel_border": "#444", "ap": "#00AA44", "ap_h": "#00CC55",
                 "dim": "#888", "rj_h": "#333", "inp_bg": "#222"}
        else:
            c = {"card_bg": "#FFFDF7", "border": "#C7A27E", "title_c": "#A9745B", "text_c": "#463329",
                 "panel": "#FFFFFF", "panel_border": "#C7A27E", "ap": "#A9745B", "ap_h": "#8A5F49",
                 "dim": "#A0856C", "rj_h": "#E4D3BC", "inp_bg": "#FFFFFF"}

        card = QWidget()
        card.setStyleSheet(f"QWidget{{background:{c['card_bg']};border:1px solid {c['border']};border-radius:6px;}}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel(strip_leading_emoji(tr("栗栗想确认一下")))
        title.setFont(ui_font(11, bold=True))
        title.setStyleSheet(f"color:{c['title_c']}; border:none; background:transparent;")
        lay.addWidget(title)

        # 逐题渲染（选项按钮 / 自由输入），控件引用收到 _question_rows 供提交时读答案
        self._question_rows = []
        for i, q in enumerate(questions):
            lay.addLayout(self._build_question_row(q, i, c))

        # 按钮行：就这个啦（提交答案）/ 跳过（等同「不知道，你看着办」）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        ok = apply_icon(QPushButton(), "circle-check", tr("✅  就这个啦"))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setFont(ui_font(11, bold=True))
        ok.setStyleSheet(f"QPushButton{{background:{c['ap']};color:#fff;border:none;border-radius:4px;padding:8px 16px;}}QPushButton:hover{{background:{c['ap_h']};}}")
        ok.clicked.connect(self._on_question_submit)
        btn_row.addWidget(ok)

        skip = QPushButton(tr("跳过"))
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.setFont(ui_font(11))
        skip.setStyleSheet(f"QPushButton{{background:transparent;color:{c['text_c']};border:1px solid {c['border']};border-radius:4px;padding:8px 16px;}}QPushButton:hover{{background:{c['rj_h']};}}")
        skip.clicked.connect(self._on_question_skip)
        btn_row.addWidget(skip)
        btn_row.addStretch()

        lay.addLayout(btn_row)

        self._msg_layout.insertWidget(self._msg_layout.count() - 1, card,
                                      alignment=Qt.AlignmentFlag.AlignLeft)
        self._question_card = card
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _build_question_row(self, q: dict, index: int, c: dict):
        """渲染一个反问：小标题 + 问题 + 选项（单选/多选 + 「其他自己写」）或自由输入。
        控件引用放进 self._question_rows，提交时据此读答案。"""
        from PySide6.QtWidgets import QLineEdit, QButtonGroup
        layout = QVBoxLayout()
        layout.setSpacing(6)
        qid = q.get("id", f"q{index}")

        header = q.get("header", "")
        if header:
            hb = QLabel(header)
            hb.setFont(ui_font(9, bold=True))
            hb.setStyleSheet(f"color:{c['dim']}; border:none; background:transparent;")
            layout.addWidget(hb)

        question_text = q.get("question", "")
        if question_text:
            ql = QLabel(question_text)
            ql.setWordWrap(True)
            ql.setFont(ui_font(10))
            ql.setStyleSheet(f"color:{c['text_c']}; border:none; background:transparent;")
            layout.addWidget(ql)

        options = q.get("options", []) or []
        multi = bool(q.get("multiSelect", False))

        # 选项按钮样式（可勾选，勾中高亮）
        opt_style = f"""
            QPushButton {{ background-color:{c['panel']}; color:{c['text_c']};
                           border:1px solid {c['panel_border']}; border-radius:4px;
                           padding:6px 12px; text-align:left; }}
            QPushButton:hover {{ border-color:{c['title_c']}; }}
            QPushButton:checked {{ background-color:{c['ap']}; color:#fff; border-color:{c['ap_h']}; }}
        """
        inp_style = f"""
            QLineEdit {{ background-color:{c['inp_bg']}; color:{c['text_c']};
                         border:1px solid {c['panel_border']}; border-radius:4px; padding:8px; }}
            QLineEdit:focus {{ border-color:{c['title_c']}; }}
        """

        if options:
            row = {"id": qid, "kind": "multi" if multi else "single",
                   "buttons": [], "other_btn": None, "other_input": None, "input": None}
            btn_group = QButtonGroup(self)
            btn_group.setExclusive(not multi)  # 单选互斥、多选非互斥

            for opt in options:
                label = opt.get("label", "") if isinstance(opt, dict) else str(opt)
                desc = opt.get("description", "") if isinstance(opt, dict) else ""
                btn_text = f"{label}\n{desc}" if desc else label
                btn = QPushButton(btn_text)
                btn.setCheckable(True)
                btn.setStyleSheet(opt_style)
                btn.setMinimumHeight(36)
                if desc:
                    btn.setMinimumHeight(52)
                btn_group.addButton(btn)
                layout.addWidget(btn)
                row["buttons"].append((btn, label))

            # 「✍️ 其他（自己写）」：勾中显示输入框，单选时跟固定选项互斥
            other_btn = apply_icon(QPushButton(), "pencil", tr("✍️ 其他（自己写）"))
            other_btn.setCheckable(True)
            other_btn.setStyleSheet(opt_style)
            other_btn.setMinimumHeight(36)
            btn_group.addButton(other_btn)
            layout.addWidget(other_btn)

            other_input = QLineEdit()
            other_input.setPlaceholderText(tr("在这里写你的回答…"))
            other_input.setStyleSheet(inp_style)
            other_input.setFont(ui_font(10))
            other_input.hide()
            layout.addWidget(other_input)
            other_btn.toggled.connect(
                lambda checked, inp=other_input: self._on_other_toggled(checked, inp))
            row["other_btn"] = other_btn
            row["other_input"] = other_input
            self._question_rows.append(row)
        else:
            row = {"id": qid, "kind": "free", "buttons": [], "other_btn": None, "other_input": None, "input": None}
            line = QLineEdit()
            line.setPlaceholderText(tr("在这里写你的回答…"))
            line.setStyleSheet(inp_style)
            line.setFont(ui_font(10))
            layout.addWidget(line)
            row["input"] = line
            self._question_rows.append(row)

        return layout

    def _on_other_toggled(self, checked: bool, input_box):
        """「其他」按钮勾选变化：勾中显示输入框并聚焦，取消则隐藏清空。"""
        if checked:
            input_box.show()
            input_box.setFocus()
        else:
            input_box.hide()
            input_box.clear()

    def _on_question_submit(self):
        """用户点「就这个啦」：收集每问答案，唤醒后台等待的干活线程。"""
        answers = []
        for row in self._question_rows:
            item = {"id": row["id"]}
            if row["kind"] == "free":
                text = (row["input"].text() if row["input"] is not None else "").strip()
                item["selected"] = []
                if text:
                    item["custom"] = text
            else:
                item["selected"] = [label for (btn, label) in row["buttons"] if btn.isChecked()]
                if row.get("other_btn") and row["other_btn"].isChecked():
                    custom = (row["other_input"].text() if row["other_input"] is not None else "").strip()
                    if custom:
                        item["custom"] = custom
            answers.append(item)
        self._finish_question(answers)

    def _on_question_skip(self):
        """用户点「跳过」：等同「不知道，你看着办」——每问都空选。"""
        answers = [{"id": row["id"], "selected": []} for row in self._question_rows]
        self._finish_question(answers)

    def _finish_question(self, answers: list):
        """答完收尾：摘卡片 + 唤醒后台等待的干活线程。"""
        self._hide_question_card()
        if self._gate_question_event is not None:
            self._gate_question_answers = answers
            self._gate_question_event.set()
            self._gate_question_event = None

    def _hide_question_card(self):
        """从消息流移除内联反问卡并清引用（幂等，可反复调用）。"""
        card = self._question_card
        self._question_card = None
        self._question_rows = []
        if card is not None:
            try:
                self._msg_layout.removeWidget(card)
                card.deleteLater()
            except Exception:
                pass

    def _update_bubble(self, idx: int):
        """只更新第 idx 个气泡文字（原地更新，不替换 widget）。
        之前这里用「删旧 widget + 插新 widget」替换气泡，会触发一次布局重建，
        流式结束后滚动位置被重置——用户正看着半截文字，突然被拉回顶部，又要重头看。
        改成跟流式 _on_stream_text 一样用 set_content 原地更新，不抖布局、不丢滚动。"""
        bubble = self._find_bubble_widget(idx)
        if bubble is not None:
            bubble.set_content(self._messages[idx]["content"])

    def _open_folder(self):
        """打开文件夹（学 VSCode 的 Open Folder）：新建 / 打开不再分开。

        选一个文件夹 → 里面有 .tamias/ 就继续旧项目（自动加载最近一条对话），
        没有就当场把它当成新项目：项目名 = 文件夹名，对话/面板数据落到 <文件夹>/.tamias/。
        文件夹即项目，用户想在哪个盘建就点哪个盘，想打开哪个就打开哪个。
        """
        folder = QFileDialog.getExistingDirectory(
            self, tr("选择项目文件夹"), "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if not folder:
            return
        self.open_project_folder(folder)

    def open_project_folder(self, folder: str) -> bool:
        """给定文件夹路径，直接把它打开成项目（跳过文件选择器）。

        供「打开文件夹」按钮和「拖拽文件到桌宠」两个入口复用，返回是否成功打开。
        核心逻辑原在 _open_folder 里，抽出为公开方法方便外部入口复用，不复制代码。
        """
        if not folder or not os.path.isdir(folder):
            return False
        # 盘符根（C:\、D:\ 等）不能当项目文件夹：dsh 建会话时会 mkdir(cwd) 确保目录
        # 存在，而盘符根本来就不能被「创建」、直接 EPERM（"failed to ensure project
        # directory"）。根目录里也放不下项目数据（.tamias），提前拦住、提示换普通文件夹。
        if is_drive_root(folder):
            QMessageBox.warning(
                self, tr("打不开文件夹"),
                tr("不能把整个盘（如 C:\\）当项目文件夹，换一个普通文件夹试试～"))
            return False
        if not self._is_project_store:
            self._slide_to(1)
            return True
        # 先记住「正在聊的对话 + 它归属的项目」，切换后优先回到它，而不是无脑跳
        # 最近更新那条（convs[0]）——否则会把用户从正在聊的旧对话硬切走，
        # 接着打字就落到「新对话」里。
        _prev_conv_id = self._current_conv.id if self._current_conv is not None else ""
        _prev_proj_id = self._current_project
        # 先保存当前还活跃的对话，再切项目（避免切换时丢未落盘的消息）
        self._sync_conv()
        existing = self._conv_store.get_project_by_folder(folder)
        if existing:
            proj = existing
        else:
            # 文件夹还没有 .tamias/ → 当成新项目（项目名取文件夹名，去尾斜杠）
            try:
                proj = self._conv_store.create_project(os.path.basename(folder), folder)
            except OSError:
                # 选到没写入权限的目录（如系统「开始菜单」目录）：mkdir .tamias 失败，
                # 兜底提示别崩，让用户换一个普通文件夹重试。
                QMessageBox.warning(
                    self, tr("打不开文件夹"),
                    tr("这个目录没有写入权限，栗栗没法在这里建项目数据（.tamias）。\n换个普通文件夹试试～"))
                return False
        self._set_current_project(proj.id, proj.work_dir)
        self.refresh_history(self._conv_store)
        # 清空聊天窗
        self._current_conv = None
        self._messages.clear()
        self._rebuild_message_widgets()
        # 有历史 → 优先回到刚才正在聊的那条（若它还属于这个项目）；否则回退最近一条。
        convs = proj.list_conversations()
        _resume_id = ""
        if _prev_conv_id and _prev_proj_id == proj.id:
            for c in convs:
                if c.id == _prev_conv_id:
                    _resume_id = c.id
                    break
        if convs:
            self._load_conversation(_resume_id or convs[0].id)
        else:
            self._add_welcome_message()
        self._slide_to(1)
        return True

    def _enter_chitchat(self):
        """进入「日常闲聊」默认项目（不绑定用户文件夹，自动存对话）。

        每次点进来都新开一条空对话（不加载历史最近一条）：当前对话悬空，
        等用户第一次真正发言时才创建 + 落盘；没说话就退出 / 再点开新对话，
        不会留下任何空对话文件。
        """
        if self._is_project_store:
            proj = self._conv_store.get_chitchat_project()
            self._set_current_project(proj.id, proj.work_dir)
            self.refresh_history(self._conv_store)
            # 新开空对话：只挂欢迎语，不创建对话文件（add_message 只在用户发言时建）
            self._current_conv = None
            self._messages.clear()
            self._rebuild_message_widgets()
            self._add_welcome_message()
        self._slide_to(1)

    def _slide_to(self, index: int):
        """切换页面：普通模式用翻页动画，专业模式用淡入（界面大，翻页太花哨）"""
        if self._pro_mode:
            self._fade_switch(index)
        else:
            self._slide_switch(index)
        if index == 0:
            self.refresh_history(self._conv_store)

    def _slide_switch(self, index: int):
        """页面翻页切换：旧页向左滑出、新页从右滑入（仅普通模式）。"""
        self._stack.slide_to(index)

    def _fade_switch(self, index: int):
        """页面淡入切换（专业模式）：新页先全透明再切过去，然后 0→1 渐入。
        比硬切柔和，又不像翻页那么花哨，适合专业模式的大界面。"""
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        # 停掉上一个还没播完的淡入，清掉旧页残留的透明效果
        if getattr(self, "_fade_anim", None) is not None:
            try:
                self._fade_anim.stop()
            except Exception:
                pass
        cur = self._stack.currentWidget()
        if cur is not None:
            cur.setGraphicsEffect(None)

        new = self._stack.widget(index)
        if new is None:
            self._stack.setCurrentIndex(index)
            return

        # 新页先全透明，切过去后视觉上还是旧页，然后渐入
        effect = QGraphicsOpacityEffect(new)
        new.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        self._stack.setCurrentIndex(index)

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(180)  # 180ms 轻轻冒出来，比翻页更轻，适合专业模式大界面
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # 播完摘掉透明效果，避免常驻占性能
        anim.finished.connect(lambda: new.setGraphicsEffect(None))
        self._fade_anim = anim  # 持有引用，防止被 GC
        anim.start()

    def _on_recent_clicked(self, item):
        """启动器最近列表点击"""
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        proj_id = item.data(Qt.ItemDataRole.UserRole + 1)
        # 模式隔离兜底：refresh_history 已按模式过滤「最近」列表，这里再拦一道，
        # 防止未来有入口绕过过滤直接塞跨模式的对话进来（专业模式不碰日常闲聊、
        # 普通模式不碰文件夹项目）。
        if proj_id:
            is_chitchat = (proj_id == CHITCHAT_PROJECT_ID)
            if self._pro_mode and is_chitchat:
                return
            if not self._pro_mode and not is_chitchat:
                return
            self._current_project = proj_id
        self._load_conversation(conv_id)
        self._slide_to(1)

    def _on_recent_context_menu(self, pos):
        """启动器最近列表右键菜单：删除 / 重命名 / 置顶（★）。"""
        item = self._recent_list.itemAt(pos)
        if not item:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        proj_id = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        conv = self._find_conv(conv_id, proj_id)
        if not conv:
            return

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_style())

        # 置顶 / 取消置顶（已置顶显示 ☆，未置顶显示 ★）
        pin_action = menu.addAction(
            tr("☆  取消置顶") if conv.pinned else tr("★  置顶"))
        rename_action = apply_icon(menu.addAction(tr("✏️  重命名")), "pencil", tr("✏️  重命名"))
        menu.addSeparator()
        delete_action = apply_icon(menu.addAction(tr("🗑  删除")), "trash-2", tr("🗑  删除"))

        chosen = menu.exec(self._recent_list.viewport().mapToGlobal(pos))
        if chosen is pin_action:
            self._toggle_pin(conv_id)
        elif chosen is rename_action:
            self._rename_history(conv_id, proj_id)
        elif chosen is delete_action:
            self._delete_history(conv_id)

    def _on_history_menu(self):
        """点历史图标 → 下拉菜单列「当前项目」的对话，点一条切换。"""
        from PySide6.QtWidgets import QMenu
        proj = self._conv_store.get_project(self._current_project or CHITCHAT_PROJECT_ID)
        convs = proj.list_conversations() if proj else []
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_style())
        if not convs:
            menu.addAction(tr("（暂无历史对话）")).setEnabled(False)
        else:
            for c in convs:  # list_conversations 已按 updated_at 倒序，最新在前
                act = menu.addAction(c.title or tr("无标题"))
                act.setCheckable(True)
                act.setChecked(self._current_conv is not None and c.id == self._current_conv.id)
                act.triggered.connect(lambda _checked, cid=c.id: self._load_conversation(cid))
        menu.exec(self._history_btn.mapToGlobal(self._history_btn.rect().bottomLeft()))

    def _find_project_for(self, conv_id: str, proj_id: str = ""):
        """找对话归属的项目（项目 store 专用：先按 proj_id 直取，再全局扫）。"""
        proj = self._history_store.get_project(proj_id) if proj_id else None
        if proj and any(c.id == conv_id for c in proj.list_conversations()):
            return proj
        for p in self._history_store.list_projects():
            if any(c.id == conv_id for c in p.list_conversations()):
                return p
        return None

    def _find_conv(self, conv_id: str, proj_id: str = ""):
        """按 id 找对话对象（兼容项目 store / 旧 store）。"""
        if not self._history_store:
            return None
        if self._is_project_store:
            proj = self._find_project_for(conv_id, proj_id)
            if proj:
                for c in proj.list_conversations():
                    if c.id == conv_id:
                        return c
            return None
        return self._history_store.get(conv_id)

    def _rename_history(self, conv_id: str, proj_id: str = ""):
        """重命名对话标题（右键菜单）。"""
        conv = self._find_conv(conv_id, proj_id)
        if not conv:
            return
        from PySide6.QtWidgets import QInputDialog
        new_title, ok = QInputDialog.getText(
            self, tr("重命名对话"), tr("输入新标题："),
            text=conv.title or "")
        if not ok:
            return
        new_title = new_title.strip()
        if not new_title:
            return
        conv.title = new_title
        if self._is_project_store:
            proj = self._find_project_for(conv_id, proj_id)
            if proj:
                proj.save_conversation(conv)
        else:
            conv.save()
        self.refresh_history(self._history_store, self._current_project)
        self._sync_conv_to_viewer()

    def _on_plan_approved(self, approved: bool):
        """用户点击批准/拒绝后执行"""
        self._deactivate_approval()
        # 门禁审批模式：唤醒后台等待的干活线程（方案 A）
        if self._gate_event is not None:
            self._gate_approved = approved
            self._gate_event.set()
            self._gate_event = None
            return
        # 旧两段式 plan→审批→执行流程（已停用，代码保留备查）
        if not approved:
            self.add_message("ai", tr("已取消～"))
            self._waiting = False
            self._send_btn.setText(tr("发送"))
            self._send_btn.setStyleSheet(self._send_btn_norm)
            self._thinking_idx = -1
            return

        self.add_message("ai", tr("$ 正在执行，稍等一下..."))
        exec_idx = len(self._messages) - 1
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        self._worker = ReplyWorker(
            lambda msg, conv_id=None, on_chunk=None, on_status=None, on_step=None, on_usage=None: self._exec_callback(msg, on_chunk=on_chunk, on_usage=on_usage),
            self._pending_plan_msg, self)
        self._worker.finished.connect(
            lambda reply: self._on_reply_done(exec_idx, reply, ok=True))
        self._worker.failed.connect(
            lambda reply: self._on_reply_done(exec_idx, reply, ok=False))
        self._worker.start()

    def _exec_callback(self, original_msg: str, on_chunk=None, on_usage=None):
        return self._on_message_callback(f"__EXEC__{original_msg}", on_chunk=on_chunk, on_usage=on_usage)

    def _sync_conv(self):
        """保存对话文件（统一存到当前项目下）。

        改成同步保存 + 固定捕获 conv 对象：对话 JSON 很小、每轮回复才写一次，
        同步写保证「切对话 / 关窗」之前内容一定落盘。之前用后台线程 + 运行时读
        self._current_conv，切对话瞬间会存错对象（或没写完就被打断），导致 AI
        回复落盘成空——切回对话时只剩用户提问、栗栗的回答全空。"""
        conv = self._current_conv
        if not conv or not self._conv_store:
            return
        conv.messages = [
            {"role": m["role"], "content": m["content"],
             "time": m.get("time", "")} for m in self._messages]
        if self._is_project_store:
            proj_id = self._current_project or CHITCHAT_PROJECT_ID
            proj = self._conv_store.get_project(proj_id)
            if proj:
                proj.save_conversation(conv)
                self._conv_store.save_project(proj)
        else:
            conv.save()

    def _on_reply_done(self, idx: int, reply: str, ok: bool = True):
        self._waiting = False
        self._stream_waiting = False  # 停止流式等待
        self._thinking_idx = -1
        self._stream_idx = -1  # 流式结束，停止增量更新
        self._set_status("")  # 隐藏标题栏状态
        self._stop_elapsed()  # 停秒表 + 隐藏 token 计数
        self._send_btn.setText(tr("发送"))
        self._send_btn.setStyleSheet(self._send_btn_norm)
        if ok:
            self._current_task_text = ""  # 成功：撤下「处理中」行
        else:
            # 失败停住：当前任务转成「失败待处置」态，排队暂停（不自动 drain）
            self._failed_task = self._current_task_text
            self._current_task_text = ""
        self._refresh_queue_panel()
        if 0 <= idx < len(self._messages):
            self._messages[idx]["content"] = reply
            self._update_bubble(idx)
            self._sync_conv()
        elif reply.strip():
            # 气泡从没创建过（干活纯工具操作、没产生文字流），补一个气泡兜底
            bubble = self.add_message("ai", reply)
            if bubble is not None:
                self._bind_meta(bubble)  # 气泡右侧挂「⏱ 秒表 · token」
        # 一轮回复结束（闲聊或干活都消耗了 token）→ 刷新余额显示，实时反映扣费
        try:
            self._viewer.refresh_balance()
        except Exception:
            pass

        # 排队：只有成功才继续取下一条（学 Claude Code：turn 结束接下一个输入）。
        # 失败则停住，等用户在面板上「重试/放弃」处置后再动，避免连环失败白烧 token。
        # 延迟一拍再发，让当前气泡/状态先完全收尾，再开下一轮。
        if ok and self._pending_queue:
            nxt = self._pending_queue.pop(0)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda t=nxt: self._send_text(t))

    # ==================== 流式打字机 ====================

    def _on_stream_text(self, text: str):
        """接收流式增量（在主线程执行）：逐段追加到正在流式的气泡。
        首个增量到达时才创建气泡（等待期间对话里不塞占位，状态在标题栏）。"""
        # 已终止或已完成 → 忽略迟到的增量
        if not self._stream_waiting:
            return
        # 第一个增量：气泡还没创建，先创建一个空的 ai 气泡承载流式文字
        if self._stream_idx < 0:
            bubble = self.add_message("ai", "")
            self._stream_idx = len(self._messages) - 1
            self._thinking_idx = self._stream_idx
            self._stream_started = False
            self._stream_buffer = ""
            if bubble is not None:
                self._bind_meta(bubble)  # 气泡右侧挂「⏱ 秒表 · token」
        if self._stream_idx >= len(self._messages):
            return
        if not self._stream_started:
            self._stream_started = True
            self._stream_buffer = text  # 覆盖空文字
        else:
            self._stream_buffer += text
        self._messages[self._stream_idx]["content"] = self._stream_buffer
        bubble = self._find_bubble_widget(self._stream_idx)
        if bubble is not None:
            bubble.set_content(self._stream_buffer)
        # 闲聊 token 实时估算：还没收到真实 usage（_task_tokens==0）时，按已输出文本
        # 粗估并显示「≈N tok」，让数字跟着文字一路涨（用户看到在动就不慌）。
        # 干活时 _task_tokens 很快被第一条 usage 顶成 >0，估算自动让位、不覆盖真实累加。
        if self._task_tokens == 0 and self._stream_buffer:
            self._token_est = max(1, len(self._stream_buffer) // 2)
            self._refresh_meta()
        self._scroll_to_bottom()

    def _find_bubble_widget(self, idx: int):
        """遍历消息布局，找到第 idx 个 _ChatBubble 控件（用于原地更新文字）。"""
        pos = 0
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            w = item.widget()
            if w and isinstance(w, _ChatBubble):
                if pos == idx:
                    return w
                pos += 1
        return None

    def _set_status(self, text: str):
        """更新标题栏「栗栗」右边的状态文字；传空字符串则隐藏。
        等待回复期间显示（正在思考/正在搜集资料…），完成/取消后隐藏。"""
        if text:
            self._status_label.setText(text)
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)
        # 广播给桌宠：皮套头顶气泡同步显示/隐藏「思考·搜索中」状态
        self.status_changed.emit(text)

    def _on_status_text(self, text: str):
        """状态信号槽（主线程执行）：底层回传一句「正在干嘛」，更新标题栏。"""
        self._set_status(text)

    # ==================== 实时秒表 + token 计数 ====================

    def _meta_text(self) -> str:
        """当前回复的元信息文案：⏱ 秒表 + token（真实值不带 ≈，闲聊估算带 ≈）。"""
        text = f"⏱ {self._elapsed_seconds}s"
        if self._task_tokens > 0:
            text += f" · {self._task_tokens} tok"
        elif self._token_est > 0:
            text += f" · ≈{self._token_est} tok"
        return text

    def _refresh_meta(self):
        """把「⏱ 秒表 · token」刷到本轮回复右侧的所有元信息承载控件上。

        注意：这里存的是气泡/过程列表「对象」（它们才有 set_meta 方法），
        不是 QLabel 子控件——传错对象会 AttributeError。"""
        if not self._meta_widgets:
            return
        text = self._meta_text()
        for widget in self._meta_widgets:
            widget.set_meta(text)

    def _bind_meta(self, widget):
        """把一个新出现的元信息承载控件（气泡/过程列表对象）挂进本轮，并立即刷一次当前值。"""
        if widget is None:
            return
        if widget not in self._meta_widgets:
            self._meta_widgets.append(widget)
        self._refresh_meta()

    def _start_elapsed(self):
        """起表：栗栗一动作就起表，元信息挂在「回复右侧」实时跳动（学 Claude Code）。
        任务启动即起表、每秒跳、结束即停，用户看数字在走就不慌。"""
        self._elapsed_seconds = 0
        self._token_est = 0
        self._meta_widgets = []  # 新一轮回复：清空上轮的元信息承载控件
        self._elapsed_timer.start()

    def _tick_elapsed(self):
        """秒表每秒 +1 并刷新右侧元信息（QTimer timeout 槽，主线程执行）。"""
        self._elapsed_seconds += 1
        self._refresh_meta()

    def _stop_elapsed(self):
        """停表（一轮回复结束 / 取消时调用）。不隐藏元信息——让最终耗时 + token 留在气泡右侧。"""
        self._elapsed_timer.stop()
        self._refresh_meta()  # 收尾刷一次，保证最终值准确

    def _on_step_event(self, state: str, label: str):
        """步骤信号槽（主线程）：在聊天流里渲染「过程列表」。
        doing=新增一行（🔄）；done/fail=给最近一行打勾/打叉。
        只处理进行中的那一轮（_stream_waiting 期间），结束后迟到的步骤事件忽略。"""
        if not self._stream_waiting:
            return
        if state == "doing":
            if self._step_list is None:
                self._step_list = _StepList(terminal=self._is_terminal(), dark=self._is_dark_theme())
                self._msg_layout.insertWidget(self._msg_layout.count() - 1, self._step_list)
                self._bind_meta(self._step_list)  # 过程列表右侧挂「⏱ 秒表 · token」
            self._step_list.add_step(label)
            self._scroll_to_bottom()
        elif self._step_list is not None:
            self._step_list.mark_last(state)

    def _on_todo_event(self, todos: list):
        """计划清单信号槽（主线程）：在聊天流里渲染/更新「计划卡」。
        每次收到 todo/write 的完整清单就整体重绘（last-write-wins，无部分更新）。
        只处理进行中的那一轮，结束后迟到的清单事件忽略。"""
        if not self._stream_waiting:
            return
        if self._plan_card is None:
            self._plan_card = PlanCard(dark=self._is_dark_theme())
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, self._plan_card)
        self._plan_card.set_todos(todos)
        self._scroll_to_bottom()

    def _on_usage_event(self, usage: dict):
        """token 用量信号槽（主线程）：干活时 dsh 每生成一条带一份 usage 逐条累加；
        闲聊在流结束时回传一份真实 usage 做「结束校准」。累加到本轮总数，同时刷新
        右侧元信息（⏱ 秒表 · token）。只处理进行中的那一轮。"""
        if not self._stream_waiting:
            return
        try:
            inp = int(usage.get("inputTokens") or 0)
            out = int(usage.get("outputTokens") or 0)
        except (TypeError, ValueError):
            return
        self._task_tokens += inp + out
        self._refresh_meta()  # 真实值，不带 ≈

    # ==================== 干活回滚 ====================

    def _resolve_work_dir(self) -> str:
        """解析当前工作目录，必须和 main.py 里 dsh 干活的 cwd 完全一致。
        因为门禁插件（Node 侧）把快照写到 <cwd>/.tamias/snapshots/，
        栗栗撤销时要用同一个目录才找得到快照。"""
        if self._settings is not None:
            return self._settings.resolve_work_dir()
        return self._working_dir or ""

    def _on_work_changed(self, changed: list):
        """干活结束回传改动清单（主线程）：弹可点击的「这次改了 N 个文件」入口。"""
        self._last_changed = changed
        self._add_work_changes_chip(changed)

    def _add_work_changes_chip(self, changed: list):
        """在消息流底部插一个可点击的「这次改了 N 个文件」小条，点开回滚对话框。"""
        self._remove_changes_chip()  # 先删旧入口（只留最近一次任务）
        n = len(changed)
        dark = self._is_dark_theme()
        if dark:
            style = ("QPushButton{background:#1A1A1A;color:#E6A23C;border:1px solid #B07B50;"
                     "border-radius:6px;padding:8px 12px;font-size:12px;}"
                     "QPushButton:hover{background:#242424;border-color:#E6A23C;}")
        else:
            style = ("QPushButton{background:#FFFDF7;color:#8B5E3C;border:1px solid #A9745B;"
                     "border-radius:6px;padding:8px 12px;font-size:12px;}"
                     "QPushButton:hover{background:#F5EDE1;border-color:#8B5E3C;}")
        chip = apply_icon(QPushButton(), "history", tr("📝 这次改了 {} 个文件 · 点我查看 / 撤销", n))
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setStyleSheet(style)
        chip.clicked.connect(lambda: self._open_rollback())
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, chip,
                                      alignment=Qt.AlignmentFlag.AlignLeft)
        self._changes_chip = chip
        self._scroll_to_bottom()

    def _remove_changes_chip(self):
        """摘掉消息流底部的「这次改了 N 个文件」入口（撤销后或新任务覆盖前调用）。"""
        if self._changes_chip is not None:
            try:
                self._msg_layout.removeWidget(self._changes_chip)
                self._changes_chip.deleteLater()
            except Exception:
                pass
            self._changes_chip = None

    def _open_rollback(self):
        """打开干活回滚对话框（文件清单 + 左右对比 + 撤销）。"""
        from PySide6.QtWidgets import QMessageBox
        from tamias.snapshot_store import SnapshotStore
        work_dir = self._resolve_work_dir()
        store = SnapshotStore(work_dir)
        if not store.has_snapshots():
            QMessageBox.information(self, tr("干活回滚"), tr("最近没有可撤销的改动哦～"))
            self._remove_changes_chip()
            return
        from tamias.rollback_dialog import RollbackDialog
        dlg = RollbackDialog(work_dir, parent=self, dark=self._is_dark_theme())
        # 记住打开的回滚窗引用：桌宠点击恢复时要把回滚窗一起拉回前台（见 restore_windows）
        self._rollback_dlg = dlg
        dlg.exec()
        self._rollback_dlg = None
        # 撤销后可能已清空快照，重新查一次决定入口去留
        if not SnapshotStore(work_dir).has_snapshots():
            self._remove_changes_chip()

    def restore_windows(self):
        """把聊天窗 + 可能开着的模态弹窗（干活回滚）一起还原到前台。
        单独最小化回滚窗后点桌宠，若只还原聊天窗，回滚窗仍最小化且模态拦着 → 界面拉不出来。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        dlg = getattr(self, "_rollback_dlg", None)
        if dlg is not None:
            dlg.showNormal()
            dlg.raise_()
            dlg.activateWindow()

    # ==================== 消息管理 ====================

    def add_message(self, role: str, content: str):
        self._messages.append({"role": role, "content": content, "time": datetime.now().isoformat()})
        # 自动保存到当前对话（普通用户也自动存，不再只限专业模式）
        if self._conv_store:
            if self._current_conv is None and role == "user":
                if self._is_project_store:
                    from tamias.project_store import Conversation
                    self._current_conv = Conversation()
                else:
                    work_dir = self._working_dir or (
                        self._settings.get("work_dir", "")
                        if self._settings else "")
                    self._current_conv = self._conv_store.create(work_dir)
            if self._current_conv:
                self._current_conv.add_message(role, content)
                # 保存到当前项目（日常闲聊也是项目，统一走这里）
                if self._is_project_store:
                    proj_id = self._current_project or CHITCHAT_PROJECT_ID
                    proj = self._conv_store.get_project(proj_id)
                    if proj:
                        proj.save_conversation(self._current_conv)
                        self._conv_store.save_project(proj)
                else:
                    self._current_conv.save()
                # 更新侧边栏 + 右侧「对话」标签页
                if role == "user":
                    self.refresh_history(self._conv_store, self._working_dir)
                    self._sync_conv_to_viewer()
        # 时间分隔线：距上一条超 5 分钟先插一条时间戳（普通模式）
        if len(self._messages) >= 2:
            self._maybe_insert_time_separator(
                self._messages[-2].get("time", "") or "",
                self._messages[-1].get("time", "") or "")
        bubble = _ChatBubble(role, content, self._pet_name, self,
                            terminal=self._is_terminal(), dark=self._is_dark_theme(),
                            scroll_area=self._scroll_area, font_size=self._chat_font_size())
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        self._animate_bubble_in(bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)
        return bubble

    def _animate_bubble_in(self, bubble):
        """新气泡淡入：0→1 渐显，配合 OutCubic 缓动，消息「浮」出来而不是硬弹出来。"""
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        effect = QGraphicsOpacityEffect(bubble)
        bubble.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        anim = QPropertyAnimation(effect, b"opacity", bubble)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # 播完摘掉透明效果，避免影响后续文本选择/重绘
        anim.finished.connect(lambda: bubble.setGraphicsEffect(None))
        # 持有引用，防止动画对象被 GC 导致半路消失
        if not hasattr(self, "_bubble_anims"):
            self._bubble_anims = []
        self._bubble_anims.append(anim)
        anim.start()

    def _scroll_to_bottom(self):
        sb = self._scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _rebuild_message_widgets(self):
        self._step_list = None  # 重建会删掉过程列表控件，引用要同步清掉（下次 doing 再建新的）
        self._plan_card = None  # 重建会删掉计划卡控件，引用同步清掉（下次 todo 事件再建新的）
        self._meta_widgets = []     # 重建会删掉气泡/过程列表控件，引用同步清掉（防悬空指针）
        self._approval_card = None       # 重建会删掉内联审批卡片，引用同步清掉（别留悬空指针）
        self._approval_approve_btn = None
        self._approval_reject_btn = None
        self._question_card = None       # 重建会删掉内联反问卡片，引用同步清掉（别留悬空指针）
        self._question_rows = []
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        prev_ts = None
        for msg in self._messages:
            cur_ts = msg.get("time", "") or ""
            if prev_ts and cur_ts:
                self._maybe_insert_time_separator(prev_ts, cur_ts)
            if cur_ts:
                prev_ts = cur_ts
            bubble = _ChatBubble(msg["role"], msg["content"],
                                 self._pet_name, self,
                                 terminal=self._is_terminal(), dark=self._is_dark_theme(),
                                 scroll_area=self._scroll_area, font_size=self._chat_font_size())
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _gap_minutes(self, prev_ts: str, cur_ts: str) -> float:
        """两条消息的时间间隔（分钟）。时间戳解析失败返回 -1（不插分隔线）。"""
        try:
            prev = datetime.fromisoformat(prev_ts)
            cur = datetime.fromisoformat(cur_ts)
            return (cur - prev).total_seconds() / 60.0
        except (ValueError, TypeError):
            return -1.0

    def _time_separator_text(self, ts: str) -> str:
        """时间分隔线文案：今天→HH:MM；昨天→『昨天 HH:MM』；更早→按界面语言日期。"""
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return ""
        now = datetime.now()
        today = now.date()
        d = dt.date()
        hm = dt.strftime("%H:%M")
        if d == today:
            return hm
        if (today - d).days == 1:
            return tr("昨天") + " " + hm
        lang = self._settings.language if self._settings else "zh-CN"
        if lang == "en":
            # 英文日期不加前导零（Sep 5 而非 Sep 05）
            return dt.strftime("%b ") + str(dt.day) if dt.year == now.year else dt.strftime("%b ") + f"{dt.day}, {dt.year}"
        # 中文/日文：月份日期不加前导零（7月27日 而非 07月27日）
        return f"{dt.month}月{dt.day}日" if dt.year == now.year else f"{dt.year}年{dt.month}月{dt.day}日"

    def _make_time_separator(self, text: str) -> QLabel:
        """时间分隔线：居中灰色小字（微信式）。"""
        lb = QLabel(text)
        lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lb.setFont(ui_font(9))
        lb.setStyleSheet("color:#B0A090; background:transparent; padding:4px 0;")
        return lb

    def _maybe_insert_time_separator(self, prev_ts: str, cur_ts: str):
        """两条消息间隔 ≥ 5 分钟时，在消息流末尾（stretch 前）插一条时间分隔线。仅普通模式。"""
        if self._is_terminal():
            return
        if not prev_ts or not cur_ts:
            return
        if self._gap_minutes(prev_ts, cur_ts) < 5:
            return
        sep = self._time_separator_text(cur_ts)
        if sep:
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, self._make_time_separator(sep))

    def _add_welcome_message(self):
        welcome = tr(
            "你好呀！我是{}～\n"
            "你可以跟我闲聊，也可以让我帮你干活哦！\n"
            "比如：\"帮我写个Python脚本\" 或 \"今天天气怎么样？\"",
            tr(self._pet_name),
        )
        self.add_message("ai", welcome)

    # ==================== 窗口控制 ====================

    def _ask_close_behavior(self):
        """首次关窗：问「留在托盘 / 彻底退出」，返回 (choice, remember)。
        choice: "tray" | "quit" | None（None = 用户点 X 关掉了弹窗）
        remember: 是否勾选「记住我的选择」
        """
        msg = QMessageBox(self)
        msg.setWindowTitle(tr("栗栗"))
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(tr("关窗后，栗栗要怎么做？"))
        msg.setInformativeText(
            tr("留在托盘：栗栗继续在桌面/托盘运行，随时能叫出来。\n"
               "彻底退出：关掉栗栗和干活引擎，不再占用文件。")
        )
        tray_btn = msg.addButton(tr("留在托盘"), QMessageBox.ButtonRole.AcceptRole)
        quit_btn = msg.addButton(tr("彻底退出"), QMessageBox.ButtonRole.ActionRole)
        msg.setDefaultButton(tray_btn)
        remember_cb = QCheckBox(tr("记住我的选择，以后不再问"))
        msg.setCheckBox(remember_cb)
        msg.exec()
        clicked = msg.clickedButton()
        remember = remember_cb.isChecked()
        if clicked is quit_btn:
            return "quit", remember
        if clicked is tray_btn:
            return "tray", remember
        return None, False

    def closeEvent(self, event):
        # 关窗行为：首次问「留在托盘 / 彻底退出」并记住（第 44 条「删不干净」根因——
        # 关窗≠退出，让用户以为退了、进程却占着文件删不掉）；之后按记住的选择走不再问。
        if getattr(self, "_quitting", False):
            # 退出进行中（quit() 关所有窗口时重入本函数），直接接受关闭，不再问
            event.accept()
            return

        behavior = self._settings.get("close_behavior", "") if self._settings else ""
        if behavior == "":
            behavior, remember = self._ask_close_behavior()
            if behavior is None:
                behavior = "tray"  # 用户关掉弹窗没选 → 默认留在托盘
            if remember and self._settings:
                self._settings.set("close_behavior", behavior)

        if behavior == "quit":
            # 彻底退出：接受关闭 + 触发应用退出（延迟到事件循环，避免 quit 重入本函数死循环）
            event.accept()
            self._quitting = True
            from PySide6.QtWidgets import QApplication
            QTimer.singleShot(0, QApplication.instance().quit)
        else:
            self.hide()
            event.ignore()

    # ==================== 历史面板 ====================

    def refresh_history(self, store, project_dir: str = ""):
        self._history_store = store
        # 只更新启动器「最近」列表（侧边栏「历史/项目」已删除，入口都归到启动器）
        if not hasattr(self, '_recent_list'):
            return
        self._recent_list.clear()
        from PySide6.QtWidgets import QListWidgetItem
        if not self._is_project_store:
            convs = store.list_by_project(project_dir) if project_dir else store.list_all()
            for c in convs:
                item = QListWidgetItem(f"{c.title or tr('无标题')}  ·  {c.date_label}")
                item.setData(Qt.ItemDataRole.UserRole, c.id)
                if c.pinned: item.setForeground(QColor("#FFD700"))
                self._recent_list.addItem(item)
            return
        for proj in store.list_projects():
            # 模式隔离：普通模式只看「日常闲聊」、专业模式只看文件夹项目，
            # 别让两种模式的对话在「最近」列表里串门（专业模式点到日常闲聊会进错项目，
            # 普通模式点到文件夹项目同理——对称的两个方向都得封）。
            if self._pro_mode:
                if proj.id == CHITCHAT_PROJECT_ID:
                    continue
            else:
                if proj.id != CHITCHAT_PROJECT_ID:
                    continue
            for c in proj.list_conversations():
                title = f"{c.title or tr('无标题')}  ·  {c.date_label}"
                if c.pinned:
                    title = f"★  {title}"
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, c.id)
                item.setData(Qt.ItemDataRole.UserRole + 1, proj.id)
                if c.pinned:
                    item.setForeground(QColor("#FFD700"))
                self._recent_list.addItem(item)

    def _toggle_pin(self, conv_id: str):
        if self._is_project_store:
            for proj in self._history_store.list_projects():
                for c in proj.list_conversations():
                    if c.id == conv_id:
                        c.pinned = not c.pinned
                        proj.save_conversation(c)
                        break
        else:
            conv = self._history_store.get(conv_id)
            if conv:
                self._history_store.pin(conv_id, not conv.pinned)
        self.refresh_history(self._history_store, self._current_project)

    def _delete_history(self, conv_id: str):
        if self._is_project_store:
            for proj in self._history_store.list_projects():
                for c in proj.list_conversations():
                    if c.id == conv_id:
                        proj.delete_conversation(conv_id)
                        break
        else:
            self._history_store.delete(conv_id)
        self.refresh_history(self._history_store, self._current_project)
        self._sync_conv_to_viewer()

    def _load_conversation(self, conv_id: str):
        if self._is_project_store:
            proj_id = self._current_project or CHITCHAT_PROJECT_ID
            proj = self._history_store.get_project(proj_id)
            conv = None
            if proj:
                for c in proj.list_conversations():
                    if c.id == conv_id:
                        conv = c; break
        else:
            conv = self._history_store.get(conv_id)
        if not conv: return
        self._current_conv = conv
        # 关键 gap 修复：加载历史对话后，同步工作目录（让 dsh/闲聊记忆跟着切到该项目 folder）
        if self._is_project_store:
            proj = self._history_store.get_project(self._current_project or CHITCHAT_PROJECT_ID)
            if proj:
                self._set_current_project(proj.id, proj.work_dir)
        self._messages.clear()
        while self._msg_layout.count() > 1:
            w = self._msg_layout.takeAt(0)
            if w.widget(): w.widget().deleteLater()
        for msg in conv.messages:
            self._messages.append({"role": msg["role"], "content": msg["content"], "time": msg.get("time", "")})
        self._rebuild_message_widgets()
        # 刷新「对话」标签页：当前对话高亮 + 列表同步
        self._sync_conv_to_viewer()

    def _on_minimize(self):
        self.hide()

    def _position_near_pet(self):
        parent = self.parent()
        if parent is None:
            return
        from PySide6.QtWidgets import QApplication
        pg = parent.frameGeometry()
        pc = pg.center()
        screen = QApplication.screenAt(pc)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        sg = screen.availableGeometry()
        lx = pg.left() - DIALOG_WIDTH - 15
        rx = pg.right() + 15
        ty = pg.top() - 50
        x = lx if lx >= sg.left() else (
            rx if rx + DIALOG_WIDTH <= sg.right() else sg.center().x() - DIALOG_WIDTH // 2)
        if ty < sg.top():
            ty = sg.top() + 20
        if ty + DIALOG_HEIGHT > sg.bottom():
            ty = sg.bottom() - DIALOG_HEIGHT - 20
        self.move(int(x), int(ty))


# ==================== 聊天气泡 ====================

# ==================== 链接自动识别（聊天正文 → 可点击超链接） ====================

# URL：http/https 开头，一路吃到空白/括号/引号，再剁掉结尾的标点（ASCII + 中文全角）
_URL_RE = re.compile(r'https?://[^\s<>"\'()]+[^\s<>"\'().,;:!?。，、；：！？…·）】』」》]')
# Windows 绝对路径：盘符:\ 或 盘符:/（只认无空格子集，先不碰含空格路径，免得误伤正文）
_WIN_PATH_RE = re.compile(r'\b[A-Za-z]:[\\/][^\s<>"\'()]+[^\s<>"\'().,;:!?。，、；：！？…·）】』」》]')


def _linkify(text: str) -> str:
    """把纯文本里的 URL / 本地绝对路径变成可点击超链接（<a href>）。
    顺序：先在原文里找 URL/路径、用 NUL 占位符顶替，再整体 HTML 转义，
    最后把占位符换回 <a>——这样 href 和正文里的 & 都不会被二次转义搞坏。"""
    if not text:
        return text
    links = []  # 每个元素 (href, 显示文字)

    def _collect(pattern, to_href, src):
        def repl(m):
            raw = m.group(0)
            idx = len(links)
            links.append((to_href(raw), raw))
            return "\x00%d\x00" % idx
        return pattern.sub(repl, src)

    text = _collect(_URL_RE, lambda p: p, text)                                 # http(s)://...
    text = _collect(_WIN_PATH_RE, lambda p: "file:///" + p.replace("\\", "/"), text)  # C:\... / C:/...
    text = html.escape(text)                                                    # 转义正文里的 <>&
    # RichText 渲染会把 \n 折叠成空格（HTML 空白折叠规则），导致回复「没有分行、段落糊成
    # 一团」——这里显式把换行换成 <br/>，保留段落层次。要在 escape 之后、链接占位符替换
    # 之前做：escape 不碰 \n，占位符是 \x00N\x00 不含 \n，两边互不干扰。
    text = text.replace("\n", "<br/>")
    for idx, (href, raw) in enumerate(links):
        text = text.replace(
            "\x00%d\x00" % idx,
            '<a href="%s">%s</a>' % (html.escape(href, quote=True), html.escape(raw)),
        )
    return text


class _SelectableLabel(QLabel):
    """可选中的文本标签：拖拽选字时，光标贴近滚动区上下边缘会自动滚屏。
    QLabel 的 TextSelectableByMouse 只会更新选区、不会滚动父 QScrollArea，
    导致「复制长消息时选区卡在可视区、滚不到下面」——这里在 mouseMove 里检测
    光标是否贴近 viewport 上下边缘，贴近就用定时器持续滚（滚到头自动停）。"""

    _EDGE = 24   # 距 viewport 上下边缘多少 px 内触发滚屏
    _STEP = 12   # 每个 tick 滚多少 px（interval 30ms → 约 400px/s）

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        # 富文本 + 链接可点：正文里的 URL / 本地路径自动变成超链接（见 _linkify）
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.linkActivated.connect(self._on_link)
        self._scroll_area = None
        self._dir = 0           # -1 上 / 0 停 / +1 下
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.setText(text)  # 走 _linkify，正文里的 URL/路径自动变超链接

    def set_scroll_area(self, sa):
        """绑定父滚动区（气泡加进消息流后由 ChatDialog 注入）。"""
        self._scroll_area = sa

    def setText(self, text: str):
        """覆盖 QLabel.setText：把正文里的 URL / 本地绝对路径自动包成可点击超链接。
        流式打字机每次 set_content 都会走到这里，代价是一次正则 + 转义，量小可忽略。"""
        super().setText(_linkify(text))

    def _on_link(self, href: str):
        """点超链接 → 浏览器开 URL / 默认程序开本地文件。"""
        try:
            # QLabel 可能把 href 里的 & 写成 &amp;，先还原再交给 QUrl
            QDesktopServices.openUrl(QUrl(href.replace("&amp;", "&")))
        except Exception:
            pass

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)  # 先让 QLabel 正常更新选区
        if self._scroll_area is None:
            return
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._update_dir(e.globalPosition().toPoint())
        else:
            self._stop()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._stop()

    def _update_dir(self, gp):
        vp = self._scroll_area.viewport()
        top = vp.mapToGlobal(vp.rect().topLeft()).y()
        bottom = vp.mapToGlobal(vp.rect().bottomRight()).y()
        if gp.y() < top + self._EDGE:
            d = -1
        elif gp.y() > bottom - self._EDGE:
            d = 1
        else:
            d = 0
        if d != self._dir:
            self._dir = d
            if d:
                self._timer.start()
            else:
                self._timer.stop()

    def _tick(self):
        if self._dir == 0 or self._scroll_area is None:
            self._timer.stop()
            return
        bar = self._scroll_area.verticalScrollBar()
        nv = bar.value() + self._dir * self._STEP
        bar.setValue(nv)
        # 滚到头就停
        if (self._dir < 0 and nv <= bar.minimum()) or (self._dir > 0 and nv >= bar.maximum()):
            self._stop()

    def _stop(self):
        self._dir = 0
        self._timer.stop()


class _ChatBubble(QWidget):
    """聊天气泡。专业模式 = VS Code 终端块，普通模式 = 粉色气泡。"""

    def __init__(self, role: str, content: str, pet_name: str,
                 parent=None, terminal: bool = False, dark: bool = False,
                 scroll_area=None, font_size: int = 13):
        super().__init__(parent)
        self._meta_lb = None  # 右侧元信息标签（⏱ 秒表 · token），仅栗栗回复气泡有
        is_user = (role == "user")
        is_plan = (role == "plan")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 1, 0, 1)

        if terminal:
            # 终端纯文本流：无背景块、无左侧竖线、无左右气泡，全部左对齐（终端不分左右）。
            # 只靠 prompt 前缀（$ 栗栗 / > 你）+ 文字颜色区分角色。
            # 专业模式深色/暖棕两种主题都走这里，结构一致、仅字色随 dark 切；普通模式走气泡分支。
            if dark:
                # 深色终端配色：绿(栗栗) / 蓝(你) / 青(计划)，黑底
                badge_c = "#666666"
                if is_user:
                    role_c, tc, prompt = "#5A8DE0", "#5A8DE0", "> "
                elif is_plan:
                    role_c, tc, prompt = "#00DDDD", "#00DDDD", "> "
                else:
                    role_c, tc, prompt = "#00FF66", "#CCCCCC", "$ "
            else:
                # 暖棕终端配色：暖棕(栗栗) / 深咖(你) / 金棕(计划)，米白底
                badge_c = "#A98B6D"
                if is_user:
                    role_c, tc, prompt = "#8B5E3C", "#8B5E3C", "> "
                elif is_plan:
                    role_c, tc, prompt = "#C08A3E", "#C08A3E", "> "
                else:
                    role_c, tc, prompt = "#A9745B", "#463329", "$ "

            wrap = QWidget()
            wrap.setMaximumWidth(BUBBLE_MAX_WIDTH_PRO)
            # Expanding：让终端块占满消息区可用宽度。否则 wordWrap 的 QLabel 会把自己的
            # sizeHint 算成很窄，把 wrap 压成「几个字宽」，出现几个字就换行的 bug。
            wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(2, 2, 2, 2)
            wl.setSpacing(1)

            # 标题行：左「$ 栗栗」+ 右「⏱ 秒表 · token」（Claude Code 风格，元信息挂回复右侧）
            hdr_row = QHBoxLayout()
            hdr_row.setContentsMargins(0, 0, 0, 0)
            hdr_row.setSpacing(6)
            hdr = QLabel(f"{prompt}{tr(pet_name) if not is_user else tr('你')}")
            hdr.setFont(mono_font(9))
            hdr.setStyleSheet(f"color:{role_c}; font-weight:bold; background:transparent;")
            hdr_row.addWidget(hdr)
            if not is_user and not is_plan:
                # 栗栗回复：右侧挂元信息（⏱ 秒表 · token），等 _refresh_meta 往里写字
                self._meta_lb = QLabel("")
                self._meta_lb.setFont(mono_font(8))
                self._meta_lb.setStyleSheet(f"color:{badge_c}; background:transparent;")
                self._meta_lb.setVisible(False)
                hdr_row.addStretch()
                hdr_row.addWidget(self._meta_lb)
            wl.addLayout(hdr_row)

            # AI 生成标识（《暂行办法》第 12 条）：非用户气泡（栗栗回复/计划）标注
            if not is_user:
                badge = QLabel(tr("AI 生成"))
                badge.setFont(mono_font(8))
                badge.setStyleSheet(f"color:{badge_c}; background:transparent;")
                wl.addWidget(badge)

            self._text_lb = _SelectableLabel(content)
            self._text_lb.set_scroll_area(scroll_area)
            self._text_lb.setWordWrap(True)
            self._text_lb.setFont(mono_font(max(7, font_size - 3)))  # 专业模式正文 = 普通字号 - 3
            self._text_lb.setStyleSheet(f"color:{tc}; background:transparent; padding:2px 0;")
            wl.addWidget(self._text_lb)

            # 纯文本流：全部左对齐（终端不分左右气泡）。wrap 已 Expanding 占满，无需再加 stretch
            outer.addWidget(wrap)
        else:
            if is_user:
                bc, tc, lt = COLOR_USER_BUBBLE, COLOR_USER_TEXT, tr("你")
            elif is_plan:
                bc, tc, lt = "#F0E0C8", "#8B5E3C", tr("计划")
            else:
                bc, tc, lt = COLOR_AI_BUBBLE, COLOR_AI_TEXT, tr(pet_name)
            al = Qt.AlignmentFlag.AlignRight if is_user else Qt.AlignmentFlag.AlignLeft

            bw = QWidget()
            bw.setMaximumWidth(BUBBLE_MAX_WIDTH)
            bw.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            bwl = QVBoxLayout(bw)
            bwl.setContentsMargins(12, 8, 12, 8)
            bwl.setSpacing(4)

            # 标题行：左「栗栗」+ 右「⏱ 秒表 · token」（跟终端模式一致，元信息挂回复右侧）
            sl_row = QHBoxLayout()
            sl_row.setContentsMargins(0, 0, 0, 0)
            sl_row.setSpacing(6)
            sl = QLabel(lt)
            sf = ui_font(10); sf.setBold(True)
            sl.setFont(sf); sl.setStyleSheet(f"color:{tc}; opacity:0.7;")
            sl.setAlignment(al)
            sl_row.addWidget(sl)
            if not is_user and not is_plan:
                self._meta_lb = QLabel("")
                self._meta_lb.setFont(mono_font(8))
                self._meta_lb.setStyleSheet(f"color:{tc}; opacity:0.7;")
                self._meta_lb.setVisible(False)
                sl_row.addStretch()
                sl_row.addWidget(self._meta_lb)
            bwl.addLayout(sl_row)

            # AI 生成标识（《暂行办法》第 12 条）：非用户气泡（栗栗回复/计划）标注
            if not is_user:
                badge = QLabel(tr("AI 生成"))
                badge.setFont(ui_font(8))
                badge.setStyleSheet("color:#B07B50;")
                badge.setAlignment(al)
                bwl.addWidget(badge)

            self._text_lb = _SelectableLabel(content)
            self._text_lb.set_scroll_area(scroll_area)
            self._text_lb.setWordWrap(True)
            self._text_lb.setFont(ui_font(font_size))  # 普通模式正文 = 设置里的绝对字号
            self._text_lb.setStyleSheet(f"color:{tc}; padding:2px;")
            self._text_lb.setAlignment(Qt.AlignmentFlag.AlignLeft)
            bwl.addWidget(self._text_lb)

            # 用户气泡深棕底自带对比；栗栗/计划气泡是浅色底，加一圈浅暖棕描边，
            # 免得在暖米白背景上「糊成一团」
            if is_user:
                bw.setStyleSheet(f"background:{bc}; border-radius:12px;")
            else:
                bw.setStyleSheet(f"background:{bc}; border:1px solid #E4D3BC; border-radius:12px;")
            if is_user:
                outer.addStretch(); outer.addWidget(bw)
            else:
                outer.addWidget(bw); outer.addStretch()

    def set_content(self, text: str):
        """原地更新气泡文字（流式打字机用，避免每 token 重建气泡）。"""
        self._text_lb.setText(text)

    def set_meta(self, text: str):
        """更新右侧元信息（⏱ 秒表 · token）；空串则隐藏。普通/计划气泡无此标签，跳过。"""
        if self._meta_lb is None:
            return
        if text:
            self._meta_lb.setText(text)
            self._meta_lb.setVisible(True)
        else:
            self._meta_lb.setVisible(False)


# ==================== 过程列表（罗列干活步骤） ====================

class _StepList(QWidget):
    """过程气泡：干活时把每一步（思考 / 工具）罗列出来，边做边打勾/打叉。
    挂在聊天流里，让主人一眼看到栗栗干到哪一步、哪步成了哪步挂了。
    行首图标：Lucide 线条图标（refresh-cw 进行中 / circle-check 成功 / circle-x 失败）。"""

    def __init__(self, terminal: bool = False, dark: bool = False, parent=None):
        super().__init__(parent)
        self._terminal = terminal
        self._dark = dark
        self._rows = []  # 每行一个 (icon_label, text_label)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 1, 0, 1)
        self._box = QWidget()
        if terminal:
            # 终端模式：过程列表跟聊天气泡一样占满消息区宽度，避免被 sizeHint 压窄
            self._box.setMaximumWidth(BUBBLE_MAX_WIDTH_PRO)
            self._box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            self._box.setMaximumWidth(BUBBLE_MAX_WIDTH)
        lay = QVBoxLayout(self._box)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)
        # 标题行：左「🛠 过程」+ 右「⏱ 秒表 · token」（元信息挂过程列表右侧，跟气泡一致）
        self._title_row = QHBoxLayout()
        self._title_row.setContentsMargins(0, 0, 0, 0)
        self._title_row.setSpacing(6)
        self._title = QLabel(strip_leading_emoji(tr("🛠 过程")))
        self._title.setFont(ui_font(10))
        self._title_row.addWidget(self._title)
        self._meta_lb = QLabel("")
        self._meta_lb.setFont(mono_font(8))
        self._meta_lb.setVisible(False)
        self._title_row.addStretch()
        self._title_row.addWidget(self._meta_lb)
        lay.addLayout(self._title_row)
        self._lay = lay
        outer.addWidget(self._box)
        if not terminal:
            outer.addStretch()
        self._apply_style()

    def _apply_style(self):
        """按主题给过程气泡上色：专业模式终端风（无框纯文本流），普通模式带暖棕框。
        字色：深色终端用绿/灰，暖棕（终端或气泡）用暖棕系。"""
        if self._terminal:
            # 终端纯文本流：去掉背景块，跟聊天气泡一致（终端风无框）
            self._box.setStyleSheet("background:transparent; border:none;")
            title_c = "#00FF66" if self._dark else "#A9745B"
            row_c = "#CCCCCC" if self._dark else "#463329"
        else:
            self._box.setStyleSheet("background:#FFFDF7; border:1px solid #E4D3BC; border-radius:12px;")
            title_c = "#A9745B"
            row_c = "#463329"
        self._title.setStyleSheet(f"color:{title_c}; font-weight:bold;")
        meta_c = "#00AA66" if (self._terminal and self._dark) else title_c
        self._meta_lb.setStyleSheet(f"color:{meta_c};")
        for _ic, tx in self._rows:
            tx.setStyleSheet(f"color:{row_c};")

    def _row_style(self) -> str:
        if self._terminal:
            return "color:#CCCCCC;" if self._dark else "color:#463329;"
        return "color:#463329;"

    def _icon_pm(self, name: str, size: int = 14):
        """把 Lucide 图标渲染成跟随主题深浅的 QPixmap（行首状态小图标用）。
        深浅取 self._dark：深色终端 → 浅色笔画，暖棕 → 深色笔画。"""
        return icon(name, size, dark=self._dark).pixmap(size, size)

    def add_step(self, label: str):
        """新增一行「进行中」的步骤：行首 refresh-cw 图标 + 文字（可换行）。"""
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        ic = QLabel()
        ic.setFixedSize(14, 14)
        ic.setPixmap(self._icon_pm("refresh-cw"))
        tx = QLabel(label)
        tx.setWordWrap(True)
        tx.setFont(ui_font(12))
        tx.setStyleSheet(self._row_style())
        tx.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        hl.addWidget(tx, 1)
        self._rows.append((ic, tx))
        self._lay.addWidget(row)

    def set_meta(self, text: str):
        """更新右侧元信息（⏱ 秒表 · token）；空串则隐藏。"""
        if text:
            self._meta_lb.setText(text)
            self._meta_lb.setVisible(True)
        else:
            self._meta_lb.setVisible(False)

    def mark_last(self, state: str):
        """给最近一行打勾（done）或打叉（fail）：把行首图标换成 circle-check/circle-x。"""
        if not self._rows:
            return
        ic, _tx = self._rows[-1]
        name = "circle-check" if state == "done" else "circle-x"
        ic.setPixmap(self._icon_pm(name))
