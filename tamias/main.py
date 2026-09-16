# ============================================================
# 栗栗（Tamias）— 应用入口
# ============================================================
# 串联所有模块：
# Settings → DeepSeek API → dsh → Gate → PetWindow → TrayIcon
# ============================================================

import os
# 虚拟机等无独立 GPU 环境下，QWebEngine 会把虚拟显卡列入 GPU 黑名单并禁用 WebGL，
# 导致 Live2D 立绘白屏（Live2D 靠 WebGL 渲染）。这里忽略黑名单 + 强制启用 WebGL，
# 让虚拟显卡尝试硬件渲染。之前的 --disable-gpu 方向反了：禁 GPU 后 WebGL 需要
# SwiftShader 软件渲染，而 QtWebEngine 6 的 SwiftShader 已弃用，反而必白屏。
# 必须在任何 Qt / PySide6 模块 import 之前设置，否则不生效。
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--ignore-gpu-blacklist --enable-webgl"
import sys
import signal
import time
from PySide6.QtWidgets import QApplication
from tamias.settings import Settings
from tamias.pet_window import PetWindow
from tamias.tray_icon import TrayIcon, load_app_icon
from tamias.i18n import tr, current_language
from tamias.snapshot_store import SnapshotStore
from tamias.app_log import log, log_gate, log_chat, crash_log_path, mask_path, log_exception
from tamias import dsh_launcher, memory_store


_instance_lock = None  # 单实例锁（重启前需正确释放，否则新进程误判「已经在运行」）


def release_instance_lock():
    """释放单实例锁。必须用 QLockFile.unlock()（关闭文件句柄 + 删锁文件）；
    os.remove 删不掉被独占打开的锁文件（Windows 上文件被占用）。"""
    global _instance_lock
    if _instance_lock is not None:
        try:
            _instance_lock.unlock()
        except Exception:
            pass


def main():
    """应用主入口"""
    # ---------- 崩溃日志兜底 ----------
    # PySide6 遇到未捕获异常会直接 abort（静默闪退，看不到任何报错）。
    # 这里挂一个 excepthook，把主线程和子线程的未捕获异常写到崩溃日志，
    # 万一栗栗再闪退，主人把这个日志发来就能一眼定位根因，而不是靠猜。
    import os as _os, traceback as _tb, threading as _th
    def _crash_hook(exc_type, exc_value, exc_tb):
        msg = "".join(_tb.format_exception(exc_type, exc_value, exc_tb))
        msg = mask_path(msg)  # 写盘前先打码用户名：打包后路径含 C:\Users\<用户名>，不脱敏会泄露
        try:
            with open(crash_log_path(), "a", encoding="utf-8") as f:
                from datetime import datetime as _dt
                f.write(f"\n[{_dt.now()}] 未捕获异常：\n{msg}\n")
        except Exception:
            pass
        sys.stderr.write(f"\n[栗栗崩溃] {msg}\n")
        sys.stderr.flush()
    sys.excepthook = _crash_hook
    _th.excepthook = lambda args: _crash_hook(args.exc_type, args.exc_value, args.exc_traceback)

    # ---------- 创建应用（先建，后面弹窗需要）----------
    app = QApplication(sys.argv)
    app.setApplicationName(tr("栗栗桌面助手"))
    app.setWindowIcon(load_app_icon())
    app.setQuitOnLastWindowClosed(False)

    # ---------- 单实例检测（QLockFile 跨进程锁，不依赖 wmic/进程名） ----------
    # 旧实现靠 wmic 查「旧实例进程名是否含 tamias」来判断是否已运行，但 Windows 11
    # 已移除 wmic 命令，检测每次都抛异常走 except → 锁失效，动画播放中退出/重启会多开实例。
    # 换成 QLockFile：纯 Qt 跨进程文件锁，正常退出自动解锁、崩溃 30 秒后判定 stale 释放，
    # 不依赖任何外部命令，也不依赖进程名（开发态 python.exe 一样能锁住）。
    import tempfile, os as _os
    from PySide6.QtCore import QLockFile
    global _instance_lock
    _lock_dir = _os.path.join(tempfile.gettempdir(), "tamias")
    _os.makedirs(_lock_dir, exist_ok=True)
    _instance_lock = QLockFile(_os.path.join(_lock_dir, "instance.lock"))
    if not _instance_lock.tryLock(100):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, tr("栗栗"),
            tr("栗栗已经在运行啦！\n请查看桌面右下角或系统托盘～"))
        sys.exit(0)
    # _instance_lock 存模块级全局，供重启前 release_instance_lock() 释放；
    # 正常退出时随事件循环结束析构，自动解锁删锁文件。

    signal.signal(signal.SIGINT, lambda *args: app.quit())

    # ---------- 加载配置 ----------
    settings = Settings()

    # ---------- 加载界面语言（i18n） ----------
    # 在创建任何界面之前就按配置切好语言，后续所有 tr() 才拿得到正确翻译。
    from tamias.i18n import set_language
    set_language(settings.language)

    # ---------- 启动日志：记版本 + 界面语言，出问题能还原「当时环境」 ----------
    from tamias import __version__
    log(f"栗栗启动 v{__version__}，界面语言 {settings.language}")

    # ---------- 浏览器弹出追踪（诊断用，定位后删） ----------
    # 启动早期就起一个后台进程创建监视器，覆盖「启动 → dsh 拉起 → 浏览器弹出」全程。
    # 复现「启动就弹 dsh 网页」后，读 logs/browser_watch.log 看浏览器进程的父进程
    # PID 是谁，即可锁定真凶（详见 browser_watch.py 模块头注释）。
    from tamias.browser_watch import start_browser_watch
    start_browser_watch()

    # ---------- 加载界面字体（中英鸿蒙 / 日文思源黑体 JP / 等宽 JetBrains Mono） ----------
    # 注册打包字体 + 按界面语言设全局默认字体；必须在创建任何控件之前调用。
    # 日语界面走 Noto Sans JP（正宗日文字形），中英界面走鸿蒙（HarmonyOS Sans SC）。
    from tamias.fonts import install_fonts, apply_app_font, ui_font
    install_fonts()
    apply_app_font(settings.language)

    # ---------- 加载提示窗：双击后立即显示，避免「加载慢以为没点中」 ----------
    # 栗栗从双击到桌宠出现要几十秒（dsh 自启 + Live2D 立绘加载），这期间桌面
    # 没有任何反馈，用户容易以为没点中、反复双击启动多个实例。这里在字体一就绪
    # 就立刻弹一个无边框加载提示窗（暖棕侦探风，跟向导/聊天统一），告诉主人
    # 「正在加载、大约半分钟到一分钟」，桌宠出现后自动关闭。
    # 不置顶、不抢焦点：首次运行的配置向导 / 协议弹窗会正常盖在它上面，交互不受影响；
    # 日常启动它直接就是桌面最前的反馈，多按的窗口会被单实例检测拦住。
    from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
    from PySide6.QtCore import Qt as _QtSplash

    class _LoadingTip(QWidget):
        """启动加载提示：紧凑小卡片，可拖动、可点右上角 × 关闭。

        之前 480x150 的大卡片堵在屏幕正中间，挡着桌面、拖不动还关不掉，难看。
        改成窄卡片（约 280px 宽、高度按内容自适应）。无边框窗口默认拖不动，这里
        手动实现拖动：按住空白 / 标题区移动、松开落下；右上角 × 让主人等得不耐烦
        随时关掉，关闭不影响后台加载，桌宠照常出现。
        """

        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                _QtSplash.WindowType.FramelessWindowHint
                | _QtSplash.WindowType.Tool
            )
            self.setAttribute(_QtSplash.WidgetAttribute.WA_ShowWithoutActivating)
            self.setStyleSheet(
                "background-color: #F5EDE1; border: 1px solid #C7A27E; border-radius: 10px;"
            )
            self._drag_offset = None  # 拖动起点：鼠标相对窗口左上角的偏移

            # 标题行：标题靠左，× 关闭按钮靠右
            _title_row = QHBoxLayout()
            _title_row.setContentsMargins(0, 0, 0, 0)
            _title_row.setSpacing(8)
            _title = QLabel(tr("栗栗正在加载..."))
            _title.setFont(ui_font(13, bold=True))
            _title.setStyleSheet("color: #463329; border: none;")
            # 让标签对鼠标「透明」，按住标题/副标题也能拖动整个卡片
            _title.setAttribute(_QtSplash.WidgetAttribute.WA_TransparentForMouseEvents)
            _title_row.addWidget(_title)
            _title_row.addStretch(1)
            _close_btn = QPushButton("×")
            _close_btn.setFixedSize(20, 20)
            _close_btn.setCursor(_QtSplash.CursorShape.PointingHandCursor)
            _close_btn.setToolTip(tr("关闭"))
            _close_btn.setStyleSheet(
                "QPushButton { color: #7A5540; background: transparent; border: none;"
                " font-size: 16px; font-weight: bold; }"
                "QPushButton:hover { color: #463329; background: #E9D8C3; border-radius: 10px; }"
            )
            _close_btn.clicked.connect(self.close)
            _title_row.addWidget(_close_btn)

            _sub = QLabel(tr("正在启动干活引擎、加载立绘\n大约需要半分钟到一分钟，请稍候～"))
            _sub.setFont(ui_font(11))
            _sub.setStyleSheet("color: #7A5540; border: none;")
            _sub.setAttribute(_QtSplash.WidgetAttribute.WA_TransparentForMouseEvents)

            _lay = QVBoxLayout(self)
            _lay.setContentsMargins(16, 12, 14, 12)
            _lay.setSpacing(6)
            _lay.addLayout(_title_row)
            _lay.addWidget(_sub)

            self.setFixedWidth(280)
            self.adjustSize()  # 高度按内容自适应

        # ---- 拖动：按住空白/标题区移动，松开落下 ----
        def mousePressEvent(self, e):
            if e.button() == _QtSplash.MouseButton.LeftButton:
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            super().mousePressEvent(e)

        def mouseMoveEvent(self, e):
            if self._drag_offset is not None and (e.buttons() & _QtSplash.MouseButton.LeftButton):
                self.move(e.globalPosition().toPoint() - self._drag_offset)
            super().mouseMoveEvent(e)

        def mouseReleaseEvent(self, e):
            self._drag_offset = None
            super().mouseReleaseEvent(e)

    _splash = _LoadingTip()
    _screen = app.primaryScreen()
    if _screen:
        _geo = _screen.availableGeometry()
        _splash.move(_geo.center().x() - _splash.width() // 2,
                     _geo.center().y() - _splash.height() // 2)
    _splash.show()
    app.processEvents()  # 立刻刷出来，别等进入事件循环

    # ---------- 中文路径自检（QWebEngine 在非 ASCII 路径下必崩，提前拦住） ----------
    # QWebEngine 的 Chromium 子进程 QtWebEngineProcess.exe 处理不了含中文等
    # 非 ASCII 字符的路径；栗栗一旦被解压到「D:\下载\栗栗\」这类目录，立绘会
    # 直接白屏、报 "Could not find QtWebEngineProcess.exe"。这里赶在真正初始化
    # QWebEngine（创建 PetWindow 时）之前，先查栗栗所在目录；含非 ASCII 就弹窗
    # 警告并退出，免得主人看到一团懵的白屏。只拦中文/日文等全角字符，不拦空格
    # （Program Files 自带空格，拦了会误伤普通安装目录）。
    import os as _os_pathcheck
    _yy_app_dir = _os_pathcheck.path.dirname(_os_pathcheck.path.realpath(sys.argv[0]))
    if any(ord(ch) > 127 for ch in _yy_app_dir):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            tr("栗栗"),
            tr("检测到栗栗放在含中文或特殊字符的路径下，这会导致立绘（Live2D）白屏无法显示。请把栗栗整个文件夹移到纯英文路径（例如 D:/Tamias），再重新启动。")
            + f"\n\n{_yy_app_dir}",
        )
        sys.exit(0)

    # ---------- 加载人设资源包（"皮"） ----------
    # 人设 + 口吻话术从 resources/persona/<名字>/ 读，换角色改 config 的 persona 字段即可。
    from tamias.persona import Persona, DEFAULT_PERSONA
    persona = Persona(settings.persona)

    def _build_chat_system_prompt(lang: str) -> str:
        """拼闲聊系统提示词 = 人设（皮 + 语言指令）+ 全局长期记忆注入。

        记忆用 build_memory_block(None) 只取全局记忆（聊天没有「项目」概念，
        不带项目级）；块为空就不追加，保持 prompt 干净、不浪费 token。
        """
        prompt = persona.build_system_prompt(lang)
        block = memory_store.build_memory_block(None)
        if block:
            prompt = prompt + "\n\n" + block
        return prompt

    # ---------- 项目存储 ----------
    from tamias.project_store import ProjectStore
    proj_store = ProjectStore()
    # 内置「日常闲聊」项目：所有对话（含闲聊）都挂它下面，启动时确保存在
    chitchat_project = proj_store.ensure_chitchat_project()

    # ---------- 首次运行：启动配置向导 ----------
    if settings.is_first_run:
        from tamias.setup_wizard import SetupWizard
        wizard = SetupWizard(settings)
        wizard.exec()  # 模态运行向导

        # 重新加载配置（向导可能已修改）
        settings.load()

    # ---------- 首次启动：勾选同意《用户协议》+《隐私政策》 ----------
    # 合规要求：协议要生效，必须让用户「明确同意」，否则免责 / 仲裁 / 责任上限
    # 这些关键条款对用户没有约束力。所以没勾过同意的（agreed_terms=False）
    # 就弹窗，勾选同意才能进主界面；不同意 / 直接关窗一律退出。
    if not settings.agreed_terms:
        from tamias.terms_dialog import show_terms_consent
        if not show_terms_consent():
            sys.exit(0)  # 用户拒绝协议 → 不进入主界面，直接退出
        settings.agreed_terms = True  # 记下已同意，下次启动不再弹

    # ---------- 创建 DeepSeek API 客户端 ----------
    deepseek_api = None
    api_key = settings.deepseek_api_key

    if api_key:
        from tamias.api.deepseek_api import DeepSeekAPI
        deepseek_api = DeepSeekAPI(
            api_key=api_key,
            api_base=settings.deepseek_api_base,
            model=settings.deepseek_model,
        )
        # 设置栗栗的角色 prompt（人设 + 按界面语言的回复语言指令）。
        # 人设从 persona 资源包读（"皮"，五锚 + 来源故事 + 语气 + 口头禅），
        # 语言指令要求回复语言完全本地化：切英文界面 → 栗栗聊天也回英文。
        deepseek_api.set_system_prompt(_build_chat_system_prompt(settings.language))
        print("[栗栗] DeepSeek API 已就绪")
    else:
        print("[栗栗] 未配置 DeepSeek API Key，聊天使用模拟回复")

    # ---------- 门禁基础设施：跨线程弹窗 + 干活前确认 ----------
    # 栗栗「门禁官」身份的核心。所有干活请求，在发给引擎之前，先在
    # 主线程弹二次元确认窗，主人批准了才真正动手（杜绝「先上车后补票」）。
    from PySide6.QtCore import QObject, Slot, QMetaObject, Qt as _QtCore

    class _MainThreadInvoker(QObject):
        """后台线程里，把一段代码切到 Qt 主线程执行并阻塞等结果（弹审批窗用）。"""
        def __init__(self):
            super().__init__()
            self._fn = None
            self._result = None

        @Slot()
        def _execute(self):
            try:
                self._result = self._fn()
            except Exception:
                self._result = False  # 弹窗出错 → 保守拒绝

        def call(self, fn):
            self._fn = fn
            self._result = None
            QMetaObject.invokeMethod(
                self, "_execute",
                _QtCore.ConnectionType.BlockingQueuedConnection,
            )
            return self._result

    _main_invoker = _MainThreadInvoker()

    # 门禁审批里的工具名 → 中文，让普通用户看得懂「栗栗要干嘛」。
    # dsh 引擎回传的是 bash/write/str_replace_editor 这类英文工具名，直接显示像乱码。
    _TOOL_NAME_CN = {
        "bash": "执行命令",
        "pwsh": "执行命令",   # Windows 上 dsh 用 pwsh 跑命令；漏掉会直接显示「pwsh」给用户
        "shell": "执行命令",
        "write": "写入文件",
        "edit": "修改文件",
        "str_replace_editor": "修改文件",
        "task": "执行任务",
        "subagent": "调度小助手",
        "skill": "调用技能",
        "create_goal": "制定计划",
        "update_goal": "更新计划",
        "web_fetch": "读取网页",
        "web_search": "搜索网页",
        "todo_write": "更新待办",
        "read": "读取文件",
    }

    def _tool_name_cn(name: str) -> str:
        """把引擎的工具名翻译成人话；不认识的原样返回（总比乱码强）。"""
        return _TOOL_NAME_CN.get(name, name)

    def _gate_confirm(message: str) -> bool:
        """干活前门禁：在聊天流内联卡片里问主人，聊天框未就绪才回退独立确认窗。"""
        # 剥离旧 __EXEC__ 前缀、截断超长，让弹窗只显示清晰的任务
        display = message[len("__EXEC__"):] if message.startswith("__EXEC__") else message
        if len(display) > 200:
            display = display[:200] + "…"

        confirm_text = tr(persona.phrase("gate_confirm_task"), display)

        def activate():
            # 优先：聊天流内联审批卡片（融入界面，不弹独立窗口、不占常驻栏）
            cd = pet.chat_dialog
            if cd is not None:
                evt = cd.request_gate_approval(confirm_text)
                if evt is not None:
                    return ("gate", evt)
            # 回退：聊天框未就绪 → 独立确认窗
            from tamias.confirm_dialog import show_confirm
            return ("dialog", show_confirm(tr(persona.phrase("gate_confirm_title")), confirm_text))

        kind, value = _main_invoker.call(activate)
        if kind == "dialog":
            return value  # 独立弹窗：value 就是 bool 结果
        # 审批栏：value 是 Event，后台线程阻塞等用户点批准/拒绝
        value.wait()
        cd = pet.chat_dialog
        return cd._gate_approved if cd is not None else False

    # ---------- DeepSeek Harness 处理函数（新墙） ----------
    # Harness 是「边干边问」：发消息 → 引擎跑 → 关键操作时发审批请求
    # → 栗栗弹窗 → 用户批准/拒绝 → 引擎继续 → 干完返回结果。
    # 这套流程打包在 DshTaskRunner（同步阻塞）里，审批弹窗用跨线程桥。
    dsh_task_runner = None
    dsh_gateway = None

    from tamias.api.dsh_client import DshGateway
    from tamias.api.dsh_backend import DshTaskRunner

    def _approval_callback(rpc_id, payload) -> bool:
        """Harness 引擎要审批时，在聊天流内联卡片里问主人，聊天框未就绪才回退独立确认窗。"""
        tool_name = _tool_name_cn(payload.get("toolName", "")) or tr("未知操作")
        reason = payload.get("reason", "") or ""   # 门禁插件给的人话：语法检查 snake.py / 删除文件 等
        # 「写记忆」触发的沙箱升级：自动批准、不弹卡。
        # 记忆文件在工作区外，dsh 要升到 danger-full-access 才能写；但写记忆是模型的可信
        # 操作（记「新名字叫什么」这种事实），主人已豁免——其它 escalate 沙箱升级照旧问。
        _rl = reason.lower()
        if _rl.startswith("escalate sandbox") and any(k in _rl for k in ("记忆", "技能", "skill", "memory")):
            log_gate(f"记忆豁免：自动批准沙箱升级｜{mask_path(reason)[:120]}")
            return True
        # 有「具体干嘛」的人话就放正文一眼可见（不再折叠成天书命令），主人直接看懂这条操作是啥
        if reason:
            title = tr(persona.phrase("approval_operation"), tool_name, reason)
        else:
            title = tr(persona.phrase("approval_operation_short"), tool_name)

        def ask():
            # 优先：聊天流内联审批卡片（融入界面，不弹独立窗口、不占常驻栏）。
            # 人话已并进正文，折叠区（detail）留空，不再堆原始命令。
            cd = pet.chat_dialog
            if cd is not None:
                evt = cd.request_gate_approval(title, detail="")
                if evt is not None:
                    return ("gate", evt)
            # 回退：聊天框未就绪 → 独立确认窗。
            # 传 parent=cd 让它定位到聊天框附近（不挡聊天界面）；cd 为 None 才居中。
            from tamias.confirm_dialog import show_confirm
            return ("dialog", show_confirm(
                tr(persona.phrase("approval_title")),
                title,
                "",
                parent=cd,
            ))

        try:
            # 栗栗递出夹纸板等主人点批准/拒绝（后台线程 emit，Qt 自动排队到主线程播动画）
            try:
                pet.approval_waiting.emit()
            except Exception:
                pass  # 皮套未就绪，忽略，不影响审批
            kind, value = _main_invoker.call(ask)
            if kind == "dialog":
                log_gate(f"门禁审批：{tool_name} → {'批准' if value else '拒绝'}｜{mask_path(reason)[:120]}")
                return value
            # 审批栏：value 是 Event，后台线程阻塞等用户点批准/拒绝
            value.wait()
            cd = pet.chat_dialog
            approved = cd._gate_approved if cd is not None else False
            log_gate(f"门禁审批：{tool_name} → {'批准' if approved else '拒绝'}｜{mask_path(reason)[:120]}")
            return approved
        finally:
            try:
                pet.approval_done.emit()
            except Exception:
                pass  # 皮套未就绪，忽略

    def _question_callback(rpc_id, payload) -> list:
        """引擎反问主人（有歧义要澄清）时，在聊天流内联卡里问，聊天框未就绪才回退弹窗。"""
        questions = payload.get("questions", []) or []

        def ask():
            # 优先：聊天流内联反问卡（融入界面，不弹独立窗口，学审批卡那套）
            cd = pet.chat_dialog
            if cd is not None:
                evt = cd.request_gate_question(questions)
                if evt is not None:
                    return ("gate", evt)
            # 回退：聊天框未就绪 → 独立选择题窗
            from tamias.question_dialog import ask_questions
            return ("dialog", ask_questions(questions, parent=cd))

        try:
            kind, value = _main_invoker.call(ask)
        except Exception:
            return []  # 弹窗出错 → 空答案，让引擎自己往下走

        if kind == "dialog":
            return value or []
        # 内联卡：value 是 Event，后台线程阻塞等用户点「就这个啦/跳过」
        value.wait()
        cd = pet.chat_dialog
        return cd._gate_question_answers if cd is not None else []

    # 记忆：按「工作目录@对话id」存会话 ID（dsh 规定同 ID 换目录会冲突，所以按目录记；
    # 再加对话 id 维度，让同一目录下每个对话各有一份独立的 dsh 会话——「＋新对话」
    # 只是另起一行、不碰旧对话的干活上下文，切回旧对话能接上）。
    def _get_session_id(cwd, conv_id=None):
        sessions = settings.get("dsh.sessions", {}) or {}
        # 读到空字符串（历史残留的无效值）时当作「没记过」返回 None、走新建路径——
        # 否则空字符串会被当成有效 id 传给引擎，引擎 `??` 对空字符串不生效、原样
        # 返回空，形成「读空→传空→返回空→存空」的死循环（测试员日志 19 次 session id 全空）。
        return sessions.get(f"{cwd}@{conv_id or ''}") or None

    def _set_session_id(cwd, conv_id, session_id):
        sessions = settings.get("dsh.sessions", {}) or {}
        sessions[f"{cwd}@{conv_id or ''}"] = session_id
        settings.set("dsh.sessions", sessions)

    # 并发保护：_init_dsh_async 后台初始化和 dsh_handler 的兜底重试可能同时进来，
    # 用非阻塞 flag 防止两个 _build_dsh 都去拉起 dsh 抢同一端口（用锁会让重试卡在
    # _wait_ready 的 180 秒空等）。已有一次 build 在跑就放弃本次，交给那次跑完。
    _dsh_building = [False]

    def _build_dsh() -> bool:
        """（重新）建立 dsh 干活链路：停旧的 → 自启引擎 → 建网关/执行器 → 同步 Key。
        返回是否成功。初始启动和用户手动刷新都走这里，保证两条路径行为一致。
        自启（start_dsh）冷启动可能慢到 180 秒，调用方按需放到后台线程避免卡 UI。"""
        nonlocal dsh_gateway, dsh_task_runner
        if _dsh_building[0]:
            return False  # 已有一次 build 在跑（可能正卡在 _wait_ready），放弃这次
        _dsh_building[0] = True
        try:
            # 刷新/重连时先把旧网关停掉，释放旧事件流线程，别留着占资源。
            # 但停网关前先取消正在跑的旧任务（置 _cancel_event 让 run() 提前返回）——
            # 只把 dsh_task_runner 置空却不 cancel，旧 runner 会变成「幽灵任务」：
            # 它收不到 turn/end（网关已停），死等满自己的 600 秒 deadline 才吐「任务超时」，
            # 而那时界面早切到新任务，这个迟到错误会被当成新任务超时。
            if dsh_task_runner is not None:
                try:
                    dsh_task_runner.cancel()
                except Exception:
                    pass
            if dsh_gateway is not None:
                try:
                    dsh_gateway.stop()
                except Exception:
                    pass
            dsh_gateway = None
            dsh_task_runner = None

            # 自启 dsh 引擎（启动即拉起）：探测/拉起，拿到实际 base_url。
            # 打包后用户没装 Node/dsh，靠 dsh_launcher 用自带便携 node 拉起；失败则干活不可用。
            base_url = dsh_launcher.start_dsh(settings)
            if not base_url:
                log("dsh 自启失败，干活功能暂不可用", "error")
                return False

            try:
                dsh_gateway = DshGateway(base_url=base_url)
                dsh_task_runner = DshTaskRunner(
                    gateway=dsh_gateway,
                    on_approval=_approval_callback,
                    on_question=_question_callback,
                    get_session_id=_get_session_id,
                    set_session_id=_set_session_id,
                )
                dsh_gateway.start()

                # 探测引擎是否真的可达（读会话列表，纯本地、不需要 Key）
                dsh_gateway.rpc.session_list()
                print("[栗栗] DeepSeek Harness 引擎已就绪（新墙）")
                log("DeepSeek Harness 引擎已就绪")

                # key 共用：把 config.yaml 里的 DeepSeek Key 同步给 dsh 干活引擎，
                # 让「闲聊 + 干活」共用一个 Key（主人只填一次）。
                # 加重试：冷启动时 session_list 刚通、credentials 端点可能还没完全
                # 就绪（首次安装 race），失败重试几次，别让一次抖动漏掉 Key 导致
                # 干活 MISSING_CREDENTIAL（结束原因 error）。
                _shared_key = settings.deepseek_api_key
                if _shared_key:
                    _key_set = False
                    for _attempt in range(3):
                        try:
                            dsh_gateway.rpc.credentials_set("DEEPSEEK_API_KEY", _shared_key)
                            _key_set = True
                            break
                        except Exception as _key_err:
                            log_exception(f"同步干活 Key 失败（第 {_attempt + 1} 次）：{_key_err}", "warning")
                            time.sleep(1)
                    if not _key_set:
                        log("同步干活 Key 3 次均失败，干活可能因缺 Key 报错", "error")
                return True
            except Exception as e:
                print(f"[栗栗] DeepSeek Harness 引擎不可达（{e}），干活功能暂不可用")
                log_exception(f"DeepSeek Harness 引擎不可达：{e}", "warning")
                try:
                    if dsh_gateway is not None:
                        dsh_gateway.stop()
                except Exception:
                    pass
                dsh_gateway = None
                dsh_task_runner = None
                return False
        finally:
            _dsh_building[0] = False

    # 初始启动：建立 dsh 干活链路（失败则干活不可用，闲聊不受影响）。
    # 包一层 try/except 兜底 start_dsh 里可能抛出的意外异常（配置损坏等），
    # 保证引擎挂了也不拖垮整机启动——闲聊走 DeepSeek API，跟 dsh 是两条独立链路。
    # ⚠️ 放后台线程跑：start_dsh 冷启动最多 60 秒，若在主线程同步跑会卡死事件循环，
    # 加载提示窗（_LoadingTip）的 × 和拖动就全点不动。后台跑后主线程立刻继续，
    # 加载窗正常响应；引擎就绪前「干活」暂不可用（点干活提示未就绪），就绪后自动可用。
    import threading

    def _init_dsh_async():
        try:
            _build_dsh()
        except Exception as e:
            print(f"[栗栗] DeepSeek Harness 初始化失败：{e}")
            log_exception(f"DeepSeek Harness 初始化失败：{e}")
            # _build_dsh 内部失败路径已把 dsh_task_runner 置空，这里不用再管

    threading.Thread(target=_init_dsh_async, daemon=True).start()

    def refresh_dsh_engine() -> bool:
        """手动刷新 dsh 干活引擎（用户自己启/关/再启 dsh 后点「刷新」重新接上）。
        返回是否成功。由聊天框在后台线程调用，避免慢启动卡 UI。"""
        ok = _build_dsh()
        if ok:
            log("手动刷新成功：dsh 干活引擎已重新接上")
        else:
            log("手动刷新失败：dsh 干活引擎未连上", "error")
        return ok

    def cancel_current_work() -> None:
        """「终止」按钮 → 打断正在 run() 的干活任务。只置取消信号、让 run() 提前返回，
        不杀 dsh 进程（引擎留着下次复用）。没任务在跑时是空操作。"""
        if dsh_task_runner is not None:
            dsh_task_runner.cancel()

    def dsh_status() -> str:
        """返回 dsh 连接状态（给聊天框状态灯用）：'ok' 已连接 / 'down' 未连接。"""
        if dsh_task_runner is None or dsh_gateway is None:
            return "down"
        try:
            dsh_gateway.rpc.session_list()
            return "ok"
        except Exception:
            return "down"

    def dsh_handler(message: str, conv_id=None, on_chunk=None, on_status=None, on_step=None, on_todo=None, on_usage=None) -> tuple:
        """干活走 Harness：同步阻塞，跑在 _ReplyWorker 的后台线程。
        返回 (成功?, 给用户的话)：成功时「话」是引擎输出（由 work_handler 加
        「任务完成啦」前缀）；失败/没连上时「话」是完整提示，不该再加前缀。
        on_chunk 是流式增量回调，dsh 边生成边推文字时逐段回传（打字机）；
        on_status 是状态回调，引擎调工具/深度思考时推一句「正在干嘛」；
        on_step 是步骤回调，引擎每开一步推 (state, label) 供聊天流罗列过程；
        on_usage 是 token 用量回调，引擎每生成一条消息推一份 usage 供 UI 累加。"""
        if dsh_task_runner is None:
            # 首次冷启动可能超时后 dsh 还在后台启动（start_dsh 超时不杀、保留进程），
            # 这里重试一次接上——若后台初始化还在跑（_dsh_building=True）会立即放弃、
            # 不重复拉起；若 dsh 已就绪（复用已起的引擎）则很快接上。跑在 _ReplyWorker
            # 后台线程，可阻塞，不影响 UI。
            try:
                _build_dsh()
            except Exception:
                pass
        if dsh_task_runner is None:
            return (False, tr(persona.phrase("engine_not_ready")))
        # 兼容旧的 __EXEC__ 前缀（chat_dialog 历史遗留）
        if message.startswith("__EXEC__"):
            message = message[len("__EXEC__"):]
        # 干活回复语言跟随界面语言：dsh 引擎自己的 prompt 是中文，栗栗这边
        # 控制不到，只能靠用户消息里带一句语言指令，让引擎用对应语言回。
        # 用户消息权重高于引擎 system prompt，模型会遵循；zh-CN 默认不加。
        lang_instr = {
            "zh-TW": "（請用繁體中文回覆）",
            "en": "Please reply in English.",
            "ja": "日本語で返信してください。",
        }.get(current_language(), "")
        if lang_instr:
            message = f"{lang_instr}\n\n{message}"
        work_dir = settings.resolve_work_dir()
        # 长期记忆注入：干活消息带上「全局 + 项目级」记忆（索引 + 正文），
        # 让引擎不用 skill 工具也能直接用上主人说过的事；块为空就跳过。
        # 项目级记忆来自 <work_dir>/.dsh/skills，只在本目录干活时带上。
        mem_block = memory_store.build_memory_block(work_dir)
        if mem_block:
            message = f"{message}\n\n{mem_block}"
        result = dsh_task_runner.run(message, cwd=work_dir, conv_id=conv_id, on_chunk=on_chunk,
                                     on_status=on_status, on_step=on_step, on_todo=on_todo,
                                     on_usage=on_usage)
        if result.get("success"):
            return (True, result["output"])
        return (False, tr(persona.phrase("engine_error"), result.get('error', '')))

    # 方案 A「任务级先问一次」开关。
    # 方案 B（dsh 内部逐操作审批）落地后，这层「车没发动就先问一次」暂时失效；
    # 想恢复方案 A 就把这里改回 True，代码完整保留、不删。
    TASK_LEVEL_GATE_ENABLED = False

    def work_handler(message: str, conv_id=None, on_chunk=None, on_status=None, on_step=None, on_todo=None, on_usage=None):
        """统一干活入口：先过门禁（主人批准才动手），只走 Harness。
        返回 (ok, text)：ok=False 表示干活失败（超时/卡死/报错/未就绪），
        供聊天框区分「失败停住排队」和「成功继续排队」。
        on_chunk 是流式增量回调、on_status 是状态回调、on_step 是步骤回调、
        on_usage 是 token 用量回调，全部透传给 dsh_handler。"""
        # 剥离"上下文拼接"前缀（"---"分隔），只拿原始任务给门禁和引擎，
        # 不让"请记住上下文"那段历史干扰门禁显示和 dsh 干活
        task = message.rsplit("\n---\n", 1)[-1].strip() if "\n---\n" in message else message
        # 门禁：干活前先问主人，批准了才把指令发给引擎（车没发动就拦）。
        # 方案 A 已失效（见上方开关），干活直接进 dsh，由 dsh 内部方案 B 逐操作审批兜底。
        if TASK_LEVEL_GATE_ENABLED and not _gate_confirm(task):
            return (False, tr(persona.phrase("work_cancelled")))
        if dsh_task_runner is not None:
            # 并发互斥快路径：上一个任务还在跑就拦下，别启动第二个 run()。
            # run() 内部还有一层忙互斥兜底，这里先给一句友好提示。
            if dsh_task_runner.is_running():
                return (False, tr("栗栗正在忙上一个任务呢，等它干完或点「终止」再喊我～"))
            # 干活回滚：本次任务开工前，清掉上一次任务留下的快照，
            # 这样 manifest 里就只剩「本次任务」的改动（主人拍板「只留最近一次任务」）。
            # 只在真要去干活时才清，引擎没连上就保留旧快照，别把可撤销的机会弄丢。
            work_dir = settings.resolve_work_dir()
            snap = SnapshotStore(work_dir)
            snap.clear()
            # 日志只记「在哪个目录干活」，不记任务原文（任务可能含用户真实信息）
            log(f"开始干活（工作目录 {mask_path(work_dir)}）")
            # 干活真正开始：发 task_started 给皮套，播「闭眼思考」动画（闲聊不播）
            try:
                pet.task_started.emit()
            except Exception:
                pass  # 皮套还没建/已销毁，忽略，不影响干活
            ok, text = dsh_handler(task, conv_id=conv_id, on_chunk=on_chunk, on_status=on_status,
                                   on_step=on_step, on_todo=on_todo, on_usage=on_usage)
            if ok:
                # 干完后把「这次改了哪些文件」的清单推给聊天框，
                # 聊天框弹出可点击的「这次改了 N 个文件」入口 → 打开回滚对比对话框。
                changed = snap.list_snapshots()
                if changed:
                    try:
                        cd = pet.chat_dialog
                        if cd is not None:
                            cd.work_changed.emit(changed)
                    except Exception:
                        pass  # 聊天框还没开/已销毁，丢弃清单不影响干活结果
                log(f"干活完成（改了 {len(changed)} 个文件，目录 {mask_path(work_dir)}）")
                return (True, tr(persona.phrase("gate_task_done"), text))
            log(f"干活失败：{text[:200]}", "error")
            return (False, text)
        return (False, tr(persona.phrase("work_engine_not_ready")))

    # ---------- 门禁层 ----------
    gate = None
    if deepseek_api:
        from tamias.gate import Gate
        gate = Gate(
            chat_api=deepseek_api,
            work_handler=work_handler,
        )
        print("[栗栗] 门禁层已就绪（AI 意图分类）")
    else:
        print("[栗栗] 门禁层未启用，使用关键词路由降级方案")

    # ---------- 消息回调（Gate 路由 或 关键词降级） ----------
    # 任务关键词（用于没有 API Key 时的降级路由）
    TASK_KEYWORDS = [
        "写", "做", "生成", "创建", "改", "修复", "重构",
        "编写", "新建", "部署", "打包", "编译", "优化",
        "帮我", "代码", "文件", "脚本", "程序",
    ]

    # ---------- 模式标记 ----------
    _always_work = [settings.get("pet.always_work", False)]
    _pro_mode = [settings.get("pet.pro_mode", False)]

    # 「记住 XXX」命令：把一句话存成长记忆（写全局记忆，对齐 Claude Code 的
    # memory 机制）。命中的消息不再走闲聊/干活路由，直接写记忆 + 回确认。
    _REMEMBER_PREFIXES = ("记住", "记下", "帮我记住", "帮我记下", "请记住", "请记下", "别忘了", "记着")

    def _try_remember(message: str):
        """尝试把消息解析成「记住 XXX」记忆命令。

        命中 → 写一条全局记忆（type=user），刷新闲聊系统提示词让新记忆立即
        生效，返回给主人的确认话；没命中 → 返回 None，走正常路由。
        """
        stripped = message.strip()
        # 去掉上下文拼接前缀（"---"分隔），只认最后一段原始用户消息
        if "\n---\n" in stripped:
            stripped = stripped.rsplit("\n---\n", 1)[-1].strip()
        matched = None
        for p in _REMEMBER_PREFIXES:
            if stripped.startswith(p):
                matched = p
                break
        if matched is None:
            return None
        # 去掉「记住」等前缀和可能的冒号，剩下的就是要记的正文
        content = stripped[len(matched):].strip().lstrip("：:").strip()
        if not content:
            return tr("记住什么呀？告诉栗栗具体内容，比如「记住：我喜欢喝拿铁」哦～")
        # 用正文前 ~20 字做索引描述，正文存完整内容；同名（同正文）覆盖
        title = content[:20].replace("\n", " ")
        try:
            memory_store.write_memory(content, content, description=title,
                                      mem_type=memory_store.TYPE_USER)
        except Exception as e:
            log_exception(f"写记忆失败：{e}", "warning")
            return tr("呜...这条记忆没存上：{}", str(e))
        # 刷新闲聊系统提示词，让新记忆立刻进上下文
        if deepseek_api is not None:
            deepseek_api.set_system_prompt(_build_chat_system_prompt(settings.language))
        log(f"记住了一条记忆：{title}")
        return tr("记住啦～栗栗会一直记得：{}", content[:50])

    def on_chat_message(message: str, conv_id=None, on_chunk=None, on_status=None, on_step=None, on_todo=None, on_usage=None):
        """用户发送消息 → 路由到对应处理器。
        返回 (ok, text)：ok=False 表示失败（超时/卡死/报错），供聊天框「失败停住排队」。
        on_chunk 是流式增量回调、on_status 是状态回调、on_step 是步骤回调、
        on_usage 是 token 用量回调，边生成边回传。"""
        # 聊天日记：记用户消息（本地回看，不进导出；原文可能含隐私，只存本地）
        log_chat(f"[用户] {message}")

        # 每次发消息前，用「当前最新记忆」重建闲聊系统提示词——记忆页增/删/改记忆后
        # 不用重启，下一条消息就带上新记忆（「记住」命令自己也会刷新，这里兜底所有来源）。
        if deepseek_api is not None:
            deepseek_api.set_system_prompt(_build_chat_system_prompt(settings.language))

        # 「记住 XXX」命令优先：写长期记忆，不走闲聊/干活路由
        remembered = _try_remember(message)
        if remembered is not None:
            log_chat(f"[栗栗] {remembered}")
            return (True, remembered)

        # 如果开启了"始终干活"，直接走干活引擎（Harness）
        if _always_work[0] and dsh_task_runner is not None:
            ok, reply = work_handler(message, conv_id=conv_id, on_chunk=on_chunk, on_status=on_status, on_step=on_step, on_todo=on_todo, on_usage=on_usage)
        elif gate:
            # 有 API Key：使用 AI 门禁层
            try:
                result = gate.process(message, conv_id=conv_id, on_chunk=on_chunk, on_status=on_status, on_step=on_step, on_todo=on_todo, on_usage=on_usage)
                ok, reply = result.get("ok", True), result["reply"]
            except Exception as e:
                ok, reply = False, tr(persona.phrase("chat_error"), str(e))
        else:
            # 无 API Key：关键词降级路由
            is_task = any(kw in message for kw in TASK_KEYWORDS)
            if is_task:
                ok, reply = work_handler(message, conv_id=conv_id, on_chunk=on_chunk, on_status=on_status, on_step=on_step, on_todo=on_todo, on_usage=on_usage)
            else:
                ok, reply = True, tr(persona.phrase("no_key_reply"), message)

        # 聊天日记：记栗栗回复
        log_chat(f"[栗栗] {reply}")
        return (ok, reply)

    def on_language_changed(lang: str):
        """界面语言切换 → 立即重设栗栗的聊天回复语言。
        清掉旧语言的多轮上下文 + 重设人设 prompt，下一次聊天就用新语言回。
        聊天回复语言即时生效；UI 文案仍需重启栗栗才刷新。"""
        if deepseek_api is None:
            return
        deepseek_api.clear_history()
        deepseek_api.set_system_prompt(_build_chat_system_prompt(lang))
        print(f"[栗栗] 回复语言已切换：{lang}")

    def on_work_mode_changed(enabled: bool):
        """切换「始终干活」模式时的回调"""
        _always_work[0] = enabled
        settings.set("pet.always_work", enabled)
        if enabled:
            print("[栗栗] 始终干活模式已开启（所有消息直接干活）")
        else:
            print("[栗栗] 始终干活模式已关闭（智能路由）")

    def on_pro_mode_changed(enabled: bool):
        """右键菜单切换专业模式时的回调"""
        _pro_mode[0] = enabled
        settings.set("pet.pro_mode", enabled)
        if enabled:
            print("[栗栗] 专业模式已开启（显示计划+深色主题）")
        else:
            print("[栗栗] 专业模式已关闭（传统界面）")

    def on_working_dir_changed(folder: str):
        """用户选择了新工作目录 或 清除会话"""
        # 会话上下文切换（新对话 / 加载旧会话 / 打开文件夹）→ 清 DeepSeek 闲聊多轮历史。
        # 根因：deepseek_api._history 是全局、跨会话累积的，切会话不清理，会把上一会话的
        # 上下文（如「用日语回复」「今天几号」）串进新会话，导致答非所问（界面对、脑子串）。
        # clear_history 会把 system 人设一起清掉，所以紧接着重设人设（同 on_language_changed）。
        # 短上下文靠 chat_dialog 拼「最近 6 条」提供，是会话隔离的，清掉全局历史安全。
        if deepseek_api is not None:
            deepseek_api.clear_history()
            deepseek_api.set_system_prompt(_build_chat_system_prompt(current_language()))
        if folder == "__CLEAR_SESSION__":
            # 「＋新对话」：只清 DeepSeek 闲聊多轮历史（上面通用部分已清），
            # 不再删 dsh 会话记忆——session 已按「目录@对话id」绑定，新对话
            # 天然产生新的空白 session，删反而会连累旧对话的干活上下文。
            print("[栗栗] 已开启新对话（闲聊历史已清，dsh 会话按对话隔离）")
            return
        settings.set("work_dir", folder)
        print(f"[栗栗] 工作目录已切换：{folder}")
        if pet._chat_dialog is not None:
            pet._chat_dialog.set_working_dir(folder)

    # ---------- 创建桌宠窗口 ----------
    pet = PetWindow(
        on_chat_message=on_chat_message,
        always_work=_always_work[0],
        pro_mode=_pro_mode[0],
        conv_store=proj_store,
        settings=settings,
        # 传「取值函数」而非快照：dsh_gateway 由后台 _build_dsh 晚些才就绪，传快照会把 None 焊死，
        # 导致桌宠右键「设置 → 填 Key」时 gateway 恒为 None、不调 credentials_set → 干活仍报
        # MISSING_CREDENTIAL（非得重启才生效）。改成 lambda 后每次打开设置都读当前最新 gateway。
        get_gateway=lambda: dsh_gateway,
        refresh_dsh=refresh_dsh_engine,
        dsh_status=dsh_status,
        on_cancel_work=cancel_current_work,
    )
    pet.work_mode_changed.connect(on_work_mode_changed)
    pet.pro_mode_changed.connect(on_pro_mode_changed)
    pet.working_dir_changed.connect(on_working_dir_changed)
    pet.language_changed.connect(on_language_changed)
    # 桌宠窗口已建好（Live2D 立绘加载完成），关闭加载提示窗
    _splash.close()
    # 延迟显示避免启动瞬间黑框闪烁；走 show_with_animation 播一次「出场」动画（渐显+动作）
    from PySide6.QtCore import QTimer
    QTimer.singleShot(100, pet.show_with_animation)

    # ---------- 内存看门狗：超阈值自动刷新立绘 + 清会话记忆 ----------
    # QWebEngine（立绘）跑久了内存越涨越大，这里周期量进程树内存，超 1.5GB
    # 就 reload 立绘（真释放）+ 清 dsh session（间接减负）。dsh 进程本身的
    # 内存回收现在做不到（它还是外部进程），等打包自启（待办 12）再做。
    from tamias.memory_watchdog import MemoryWatchdog, process_tree_working_set_mb

    def _reclaim_memory(mb):
        # 刷新 Live2D 立绘——看门狗唯一真能释放内存的动作（杀 Chromium 子进程）。
        # 之前这里还「清 dsh session」，但那只是删 settings 里的 session_id 映射，
        # 既不释放 dsh（常驻 node 进程）内存、也不删磁盘会话文件，还让用户下次
        # 干活丢上下文，名不副实，已移除。
        try:
            pet.reload_live2d()
        except Exception:
            log_exception("内存看门狗：刷新立绘失败")
            return  # 立绘没刷成，验证回收效果没意义，直接返回

        def _verify_reclaim():
            # 延迟 5 秒再量：reload 后 Chromium 子进程要几秒才退干净，立即量还是旧值。
            try:
                after = process_tree_working_set_mb()
            except Exception:
                log("内存看门狗：回收后量内存失败", "warning")
                return
            dropped = mb - after
            if dropped > 0:
                log(f"内存看门狗：内存 {mb:.0f}MB 超阈值，已刷新立绘，回收后 {after:.0f}MB（降 {dropped:.0f}MB）")
            else:
                log(f"内存看门狗：内存 {mb:.0f}MB 超阈值，已刷新立绘但回收后仍 {after:.0f}MB（未降，泄漏大头疑似在主进程）", "warning")

        QTimer.singleShot(5000, _verify_reclaim)

    _watchdog = MemoryWatchdog(threshold_mb=1536)
    _watchdog.set_reclaim_callback(_reclaim_memory)
    _watchdog.start()

    print("[栗栗] 桌宠已启动！")
    print("[栗栗] - 拖拽：用鼠标拖动栗栗")
    print("[栗栗] - 点击：戳一下栗栗，弹出聊天对话框")
    print("[栗栗] - 闲聊：日常聊天 → DeepSeek API")
    print("[栗栗] - 干活：写代码/改文件 → DeepSeek Harness")
    print("[栗栗] - 托盘：右键托盘图标显示菜单")
    print("[栗栗] - 退出：通过托盘菜单退出")

    # ---------- 设置对话框 ----------
    def open_settings():
        """打开设置对话框（填/显/删 API Key 等）。"""
        from tamias.settings_dialog import SettingsDialog
        dlg = SettingsDialog(settings, gateway=dsh_gateway)
        dlg.exec()

    # ---------- 资源库对话框 ----------
    def open_resource_library():
        """打开资源库对话框（换人设/皮肤）。"""
        from tamias.resource_library import ResourceLibrary
        dlg = ResourceLibrary(settings, parent=None)
        dlg.exec()

    # ---------- 日志导出 ----------
    def export_logs_callback():
        """一键导出异常日志：打包 logs/ 成 zip 存桌面，弹窗提示发给作者。"""
        try:
            from tamias.log_exporter import export_logs, show_export_success
            zip_path = export_logs()
            show_export_success(None, zip_path)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, tr("栗栗"), tr("导出异常日志失败：{}", str(e)))

    # ---------- 创建系统托盘图标 ----------
    tray = TrayIcon(pet, app, settings_callback=open_settings,
                    resource_callback=open_resource_library,
                    log_export_callback=export_logs_callback,
                    refresh_dsh_callback=refresh_dsh_engine)

    # 定时提醒到点 → 托盘也弹一条通知（桌宠气泡由 pet 自己弹，这里补托盘双保险）
    pet.reminder.remind.connect(
        lambda text: tray.showMessage(tr("栗栗"), tr("⏰ 时间到：{}", text))
    )

    # ---------- 退出时停掉自启的 dsh 引擎（复用别人的不杀）----------
    app.aboutToQuit.connect(dsh_launcher.stop_dsh)

    # ---------- 进入事件循环 ----------
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
