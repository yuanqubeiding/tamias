# ============================================================
# 栗栗（Tamias）— 系统托盘图标
# ============================================================
# 在 Windows 系统托盘中显示栗栗图标。
# 支持右键菜单（显示/隐藏、设置、退出）和双击切换显示。
# 图标通过程序动态生成（后期可替换为真实图标文件）。
# ============================================================

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QPixmap, QPainter, QActionGroup
from PySide6.QtCore import Qt, QSize, Signal, QTimer

import os
import threading

from tamias.i18n import tr
from tamias.ui_icons import apply_icon, icon, strip_leading_emoji, draw_chestnut


# ---------- 常量 ----------

# 托盘图标大小（像素）
ICON_SIZE = 32

# 应用图标文件（暖米棕背景 PNG），托盘/窗口/任务栏共用
ICON_PATH = os.path.join(os.path.dirname(__file__), "resources", "icon", "tamias_icon.png")


def _create_tray_icon_pixmap() -> QPixmap:
    """兜底托盘图标：画一颗栗子占位（真图标 PNG 缺失时触发）。

    不画脸——代码手绘二次元脸必然粗糙；画栗子没有五官可丑，还贴「栗栗」这个名字。
    """
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 栗子半径 12，略下沉一点，留出顶部小蒂的空间
    draw_chestnut(painter, ICON_SIZE / 2, ICON_SIZE / 2 + 1, 12)
    painter.end()
    return pixmap


def load_app_icon() -> QIcon:
    """
    加载栗栗应用图标（暖米棕背景 PNG）。
    供托盘图标、主窗口、任务栏共用；文件缺失时退回 QPainter 画的旧图标。
    """
    if os.path.exists(ICON_PATH):
        return QIcon(ICON_PATH)
    return QIcon(_create_tray_icon_pixmap())


class TrayIcon(QSystemTrayIcon):
    """
    栗栗系统托盘图标
    ---------------
    提供系统托盘的图标和菜单。
    功能：
    - 右键菜单：显示/隐藏栗栗、设置、退出
    - 双击图标：切换显示/隐藏
    """

    # 后台线程 emit「dsh 重启结果」→ 主线程弹托盘气泡（跨线程更新 UI 只能走信号）
    _dsh_restarted = Signal(bool)

    def __init__(self, pet_window, parent=None, settings_callback=None, resource_callback=None,
                 log_export_callback=None, refresh_dsh_callback=None):
        """
        Args:
            pet_window: PetWindow 实例，用于显示/隐藏控制 + 语言/模式切换
            parent: 父 QObject
            settings_callback: 点击「API Key」时调用的函数（打开设置对话框），
                               为 None 时保留旧提示（还没接界面）。
            resource_callback: 点击「资源库」时调用的函数（打开资源库对话框），
                               为 None 时保留旧提示。
            log_export_callback: 点击「导出异常日志」时调用的函数（打包日志成 zip 存桌面），
                               为 None 时保留旧提示。
            refresh_dsh_callback: 点击「启动/重连干活引擎」时调用的函数（后台线程拉起 dsh，
                               返回是否成功），为 None 时不显示该入口。
        """
        super().__init__(parent)

        # 保存引用
        self._pet_window = pet_window
        self._settings_callback = settings_callback
        self._resource_callback = resource_callback
        self._log_export_callback = log_export_callback
        self._refresh_dsh_callback = refresh_dsh_callback  # 手动启动/重连 dsh 回调（后台线程跑）
        self._dsh_restarting = False  # 防连点：正在重启 dsh 时忽略再次触发

        # ---------- 设置图标 ----------
        self.setIcon(load_app_icon())

        # ---------- 提示文本 ----------
        self.setToolTip(tr("栗栗 - 桌面智能助手"))

        # ---------- 右键菜单 ----------
        self._create_menu()

        # ---------- 单击打开工作界面 / 双击切换显示/隐藏 ----------
        self.activated.connect(self._on_activated)
        # 单击/双击区分：Windows 双击会先发一次单击（Trigger），用短定时器延迟单击动作，
        # 若 250ms 内等来双击就取消，避免双击切立绘时工作界面也跟着闪出来
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.setInterval(250)
        self._single_click_timer.timeout.connect(self._on_single_click)

        # ---------- dsh 重启结果 → 主线程弹气泡 ----------
        self._dsh_restarted.connect(self._on_dsh_restarted)

        # ---------- 显示托盘图标 ----------
        self.show()

        print("[栗栗] 系统托盘图标已就绪")

    def _create_menu(self):
        """创建右键菜单（设置 → 子菜单：语言/Key/专业模式/始终干活/资源库）。"""
        menu = QMenu()

        # 显示/隐藏
        self._toggle_action = menu.addAction(tr("隐藏栗栗"))
        self._toggle_action.triggered.connect(self._toggle_visibility)

        menu.addSeparator()

        # ---------- 设置子菜单 ----------
        self._settings_menu = menu.addMenu(strip_leading_emoji(tr("⚙️ 设置")))
        self._settings_menu.setIcon(icon("settings", 16))

        # 语言子菜单（4 语言单选打勾）
        lang_menu = self._settings_menu.addMenu(strip_leading_emoji(tr("🌐 语言")))
        lang_menu.setIcon(icon("languages", 16))
        lang_group = QActionGroup(lang_menu)
        self._lang_actions = {}
        for label, code in (("简体中文", "zh-CN"), ("繁體中文", "zh-TW"),
                            ("English", "en"), ("日本語", "ja")):
            action = lang_menu.addAction(label)
            action.setCheckable(True)
            action.setData(code)
            action.triggered.connect(lambda checked, c=code: self._pet_window.set_language(c))
            lang_group.addAction(action)
            self._lang_actions[code] = action

        # API Key
        key_action = apply_icon(self._settings_menu.addAction(tr("🔑 API Key")), "key", tr("🔑 API Key"))
        key_action.triggered.connect(self._on_settings)

        self._settings_menu.addSeparator()

        # 专业模式（checkable）
        self._pro_action = apply_icon(self._settings_menu.addAction(tr("⚡ 专业模式")), "zap", tr("⚡ 专业模式"))
        self._pro_action.setCheckable(True)
        self._pro_action.triggered.connect(self._pet_window.set_pro_mode)

        # 始终干活（checkable）
        self._work_action = apply_icon(self._settings_menu.addAction(tr("🔧 始终干活")), "wrench", tr("🔧 始终干活"))
        self._work_action.setCheckable(True)
        self._work_action.triggered.connect(self._pet_window.set_work_mode)

        # 开机自启动（checkable）
        self._autostart_action = apply_icon(self._settings_menu.addAction(tr("🚀 开机自启动")), "rocket", tr("🚀 开机自启动"))
        self._autostart_action.setCheckable(True)
        self._autostart_action.triggered.connect(self._pet_window.set_auto_start)

        # 手动启动/重连干活引擎（dsh 挂掉 / 手动关掉后点这里重新拉起）
        if self._refresh_dsh_callback is not None:
            self._restart_dsh_action = self._settings_menu.addAction(tr("🔄 启动/重连干活引擎"))
            self._restart_dsh_action.triggered.connect(self._on_restart_dsh)

        self._settings_menu.addSeparator()

        # 资源库
        library_action = apply_icon(self._settings_menu.addAction(tr("🎨 资源库")), "palette", tr("🎨 资源库"))
        library_action.triggered.connect(self._on_resource)

        self._settings_menu.addSeparator()

        # 导出异常日志（出问题时一键打包发给作者）
        export_action = apply_icon(self._settings_menu.addAction(tr("📋 导出异常日志")), "clipboard", tr("📋 导出异常日志"))
        export_action.triggered.connect(self._on_export_logs)

        self._settings_menu.addSeparator()

        # 重启栗栗
        restart_action = apply_icon(self._settings_menu.addAction(tr("🔄 重启栗栗")), "refresh-cw", tr("🔄 重启栗栗"))
        restart_action.triggered.connect(self._pet_window.restart_app)

        menu.addSeparator()

        # 退出
        exit_action = menu.addAction(tr("退出"))
        exit_action.triggered.connect(self._on_exit)

        # 每次弹出前刷新勾选状态（桌宠右键改状态后托盘菜单不残留旧勾选）
        menu.aboutToShow.connect(self._refresh_states)

        self.setContextMenu(menu)

    def _on_activated(self, reason):
        """
        托盘图标被激活（单击/双击）。

        Args:
            reason: 激活原因（DoubleClick, Trigger 等）
        """
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # 单击 = 打开/恢复工作界面（聊天/干活窗口）。延迟 250ms 执行，等双击来则取消
            # （Windows 双击会先发一次 Trigger，直接执行会跟双击切立绘撞车）
            self._single_click_timer.start()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._single_click_timer.stop()  # 取消待执行的单击动作
            self._toggle_visibility()

    def _on_single_click(self):
        """单击托盘（250ms 内没等到双击）→ 打开/恢复工作界面。"""
        self._pet_window.open_chat_dialog()

    def _toggle_visibility(self):
        """切换栗栗的显示/隐藏状态（以立绘实际可见性为准，兼容桌宠右键「隐藏栗栗」）"""
        if self._pet_window.isVisible():
            self._pet_window.hide_with_animation()
            self._toggle_action.setText(tr("显示栗栗"))
        else:
            self._pet_window.show_with_animation()
            self._toggle_action.setText(tr("隐藏栗栗"))

    def _on_settings(self):
        """打开 API Key 设置对话框。"""
        if self._settings_callback is not None:
            self._settings_callback()
        else:
            print("[栗栗] 设置功能尚未接线（settings_callback 未传入）")

    def _on_resource(self):
        """打开资源库对话框（换人设/皮肤）。"""
        if self._resource_callback is not None:
            self._resource_callback()
        else:
            print("[栗栗] 资源库功能尚未接线（resource_callback 未传入）")

    def _on_export_logs(self):
        """导出异常日志（打包 logs/ 成 zip 存桌面，弹窗提示发给作者）。"""
        if self._log_export_callback is not None:
            self._log_export_callback()
        else:
            print("[栗栗] 导出异常日志功能尚未接线（log_export_callback 未传入）")

    def _refresh_states(self):
        """弹出菜单前刷新语言打勾 + 专业/始终干活/开机自启勾选 + 显示/隐藏文字，跟桌宠当前状态对齐。"""
        cur_lang = self._pet_window.language
        for code, action in self._lang_actions.items():
            action.setChecked(code == cur_lang)
        self._pro_action.setChecked(self._pet_window.pro_mode)
        self._work_action.setChecked(self._pet_window.always_work)
        self._autostart_action.setChecked(self._pet_window.auto_start)
        # 显示/隐藏文字跟随立绘实际可见性（桌宠右键「隐藏栗栗」也可能改状态）
        self._toggle_action.setText(tr("隐藏栗栗") if self._pet_window.isVisible() else tr("显示栗栗"))

    def _on_restart_dsh(self):
        """手动启动/重连干活引擎（后台线程拉起，避免 start_dsh 慢启动卡 UI）。"""
        if self._refresh_dsh_callback is None or self._dsh_restarting:
            return  # 没接回调 / 正在重启中，忽略连点
        self._dsh_restarting = True
        threading.Thread(target=self._run_restart_dsh, daemon=True).start()

    def _run_restart_dsh(self):
        """后台线程：调用重启回调，结果通过信号送回主线程弹气泡。"""
        try:
            ok = bool(self._refresh_dsh_callback())
        except Exception:
            ok = False
        self._dsh_restarted.emit(ok)

    def _on_dsh_restarted(self, ok: bool):
        """重启完成（主线程）：解除防连点 + 按结果弹托盘气泡。"""
        self._dsh_restarting = False
        if ok:
            self.showMessage(tr("栗栗"), tr("干活引擎已启动 ✅"),
                             QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            self.showMessage(tr("栗栗"), tr("干活引擎启动失败，请稍后再试"),
                             QSystemTrayIcon.MessageIcon.Warning, 4000)

    def _on_exit(self):
        """退出应用：走桌宠的退出流程（先播告别动画，渐隐后关窗退出）。"""
        print("[栗栗] 正在退出...")
        self._pet_window._on_exit()
