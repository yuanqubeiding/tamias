# ============================================================
# 栗栗（Tamias）— 设置对话框
# ============================================================
# 托盘菜单「设置...」打开的真实设置界面。
#
# 现在只有一块：DeepSeek API Key 的「填 / 显 / 删」。
# 一套 Key 两张嘴：
#   1. 闲聊 → config.yaml 的 deepseek.api_key（栗栗自己的 DeepSeek 客户端）
#   2. 干活 → dsh 引擎的 DEEPSEEK_API_KEY 凭据（credentials.set/unset）
# 所以保存/删除要双写两边；dsh 引擎没开时只写 config.yaml，并提示用户。
# ============================================================

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QCheckBox,
)
from PySide6.QtGui import QFont

from tamias.i18n import tr
from tamias.fonts import ui_font, mono_font
from tamias.ui_icons import apply_icon
from tamias.theme import WARM as _C


def _mask_key(key: str) -> str:
    """把 Key 打码成 sk-...后4位，用于「已配置」状态的友好预览。"""
    key = key.strip()
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "****"
    return key[:6] + "..." + key[-4:]


class SettingsDialog(QDialog):
    """
    栗栗设置对话框。

    目前只有 API Key 的填/显/删。后续可在这加更多分组（外观、开关等）。

    Args:
        settings: 栗栗 Settings 实例（读写 config.yaml）
        gateway: DshGateway 实例或 None（引擎没开时 None，双写降级为只写 config.yaml）
    """

    def __init__(self, settings, gateway=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._gateway = gateway  # 可能为 None

        self.setWindowTitle(tr("栗栗设置"))
        self.setMinimumWidth(440)
        self.setModal(True)
        # 暖棕侦探风背景，跟聊天普通模式统一（呼应 chat_dialog 的 COLOR_BG）
        self.setStyleSheet(f"QDialog {{ background: {_C['bg']}; }}")

        self._build_ui()
        self._load_current_key()

    # ---------- 界面搭建 ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("DeepSeek API Key")
        title.setFont(ui_font(13, bold=True))
        title.setStyleSheet(f"color: {_C['title']};")  # 标题暖棕，呼应聊天标题
        layout.addWidget(title)

        # 说明（一套 Key 两张嘴）
        desc = QLabel(
            tr(
                "这个 Key 栗栗会同时用在两处：\n"
                "　· 聊天（跟你日常说话）\n"
                "　· 干活（写代码 / 改文件，走 DeepSeek Harness）\n\n"
                "获取方式：<a href='https://platform.deepseek.com'>platform.deepseek.com</a> "
                "→ 注册登录 → API Keys 页面创建 Key → 复制粘贴到下方。"
            )
        )
        desc.setWordWrap(True)
        desc.setOpenExternalLinks(True)
        desc.setFont(ui_font(10))
        desc.setStyleSheet(f"color: {_C['text']};")  # 深咖说明文字
        layout.addWidget(desc)

        # 输入框
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("sk-xxxxxxxxxxxxxxxx")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setFont(mono_font(11))
        # 输入框白底 + 浅暖棕边框，呼应聊天输入框
        self._api_key_input.setStyleSheet(
            f"QLineEdit {{ background: {_C['white']}; color: {_C['text']}; border: 2px solid {_C['border']}; "
            f"border-radius: 8px; padding: 8px; }}"
            f"QLineEdit:focus {{ border-color: {_C['primary']}; }}"
        )
        layout.addWidget(self._api_key_input)

        # 显示/隐藏 + 状态行
        row = QHBoxLayout()
        row.setSpacing(8)

        self._show_btn = apply_icon(QPushButton(), "eye", tr("👁 显示 Key"))
        self._show_btn.setFixedWidth(120)
        self._show_btn.setStyleSheet(self._btn_style())
        self._show_btn.clicked.connect(self._toggle_visibility)
        row.addWidget(self._show_btn)

        self._status_label = QLabel("")
        self._status_label.setFont(ui_font(9))
        self._status_label.setStyleSheet(f"color: {_C['muted']};")  # 浅暖棕状态
        row.addWidget(self._status_label)
        row.addStretch()

        layout.addLayout(row)

        # 保存 / 删除
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._save_btn = apply_icon(QPushButton(), "save", tr("💾 保存 Key"))
        self._save_btn.setStyleSheet(self._primary_btn_style())
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        self._delete_btn = apply_icon(QPushButton(), "trash-2", tr("🗑 删除 Key"))
        self._delete_btn.setStyleSheet(self._danger_btn_style())
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(f"color: {_C['divider']};")  # 浅暖棕分隔线
        layout.addWidget(line)

        # 干活行为开关
        work_title = QLabel(tr("干活行为"))
        work_title.setFont(ui_font(12, bold=True))
        work_title.setStyleSheet(f"color: {_C['title']};")
        layout.addWidget(work_title)

        self._work_persona_cb = QCheckBox(tr("干活时用栗栗人设"))
        self._work_persona_cb.setChecked(bool(self._settings.work_persona))
        self._work_persona_cb.setFont(ui_font(11))
        self._work_persona_cb.setStyleSheet(f"color: {_C['text']};")
        self._work_persona_cb.stateChanged.connect(self._on_work_persona_toggled)
        layout.addWidget(self._work_persona_cb)

        work_hint = QLabel(
            tr(
                "· 勾上：栗栗办事时保持「松鼠侦探管家」的口吻和身份。\n"
                "· 不勾：干活变回纯工具腔（更省 token，适合嫌人设啰嗦的）。\n"
                "· 改动后重启栗栗才生效。"
            )
        )
        work_hint.setWordWrap(True)
        work_hint.setFont(ui_font(9))
        work_hint.setStyleSheet(f"color: {_C['muted']};")
        layout.addWidget(work_hint)

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        line2.setStyleSheet(f"color: {_C['divider']};")
        layout.addWidget(line2)

        # 按键说明：读 prompt_library.SHORTCUTS 这张表（集中一处，以后加按键只改那张表）
        shortcut_title = QLabel(tr("按键说明"))
        shortcut_title.setFont(ui_font(12, bold=True))
        shortcut_title.setStyleSheet(f"color: {_C['title']};")
        layout.addWidget(shortcut_title)

        from tamias.prompt_library import SHORTCUTS
        for key, action, when in SHORTCUTS:
            row = QHBoxLayout()
            row.setSpacing(10)
            key_lb = QLabel(key)
            key_lb.setFont(mono_font(10))
            key_lb.setFixedWidth(110)
            key_lb.setStyleSheet(f"color: {_C['primary']};")
            row.addWidget(key_lb)
            desc_lb = QLabel(f"{tr(action)}　·　{tr(when)}")
            desc_lb.setWordWrap(True)
            desc_lb.setFont(ui_font(9))
            desc_lb.setStyleSheet(f"color: {_C['text']};")
            row.addWidget(desc_lb, 1)
            layout.addLayout(row)

        # 提示
        hint = QLabel(
            tr(
                "💡 小提示：\n"
                "· Key 只存在你自己电脑的 config.yaml 和引擎凭据里，别把 config.yaml 发给别人。\n"
                "· 删除 Key 后，栗栗的聊天会退回模拟回复，干活会提示没有 Key，不会出错崩溃。\n"
                "· 改动 Key 后重启栗栗才会完全生效。"
            )
        )
        hint.setWordWrap(True)
        hint.setFont(ui_font(9))
        hint.setStyleSheet(f"color: {_C['muted']};")  # 浅暖棕提示
        layout.addWidget(hint)

        # 关闭
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton(tr("关闭"))
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(self._btn_style())
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ---------- 样式 ----------

    @staticmethod
    def _btn_style() -> str:
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {_C['title']};
                border: 1px solid {_C['border']};
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {_C['hover_bg']}; }}
        """

    @staticmethod
    def _primary_btn_style() -> str:
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
        """

    @staticmethod
    def _danger_btn_style() -> str:
        return f"""
            QPushButton {{
                background-color: {_C['danger_bg']};
                color: {_C['danger']};
                border: 1px solid {_C['danger_border']};
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {_C['danger_hover']}; }}
        """

    # ---------- 数据 ----------

    def _load_current_key(self):
        """打开时把已保存的 Key 填进输入框，并更新状态标签。"""
        key = self._settings.deepseek_api_key or ""
        self._api_key_input.setText(key)
        self._update_status()

    def _on_work_persona_toggled(self, state):
        """勾选/取消「干活时用栗栗人设」→ 立即存盘（重启栗栗后生效）。"""
        self._settings.work_persona = bool(state)

    def _update_status(self):
        key = self._settings.deepseek_api_key or ""
        if key:
            self._status_label.setText(tr("已配置：{}", _mask_key(key)))
        else:
            self._status_label.setText(tr("未配置"))

    def _toggle_visibility(self):
        """切换 Key 显示/隐藏"""
        if self._api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self._api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            apply_icon(self._show_btn, "eye-off", tr("🙈 隐藏 Key"))
        else:
            self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            apply_icon(self._show_btn, "eye", tr("👁 显示 Key"))

    # ---------- 动作 ----------

    def _on_save(self):
        """保存：双写 config.yaml（闲聊）+ dsh 凭据（干活）。"""
        key = self._api_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "栗栗", tr("Key 不能为空哦，请先粘贴进去~"))
            return

        # 1. 写 config.yaml（闲聊）
        self._settings.deepseek_api_key = key
        self._update_status()

        # 2. 写 dsh 凭据（干活），引擎没开就只写一半并提醒
        dsh_note = ""
        if self._gateway is not None:
            try:
                self._gateway.rpc.credentials_set("DEEPSEEK_API_KEY", key)
                dsh_note = tr("干活引擎（DeepSeek Harness）已同步更新。")
            except Exception as e:
                dsh_note = tr("干活引擎没连上（{}），暂时只存了聊天这份，等引擎启动后再设一次。", e)
        else:
            dsh_note = tr("干活引擎当前没启动，暂时只存了聊天这份，等它启动后再设一次。")

        QMessageBox.information(
            self, "栗栗",
            tr("Key 已保存！\n\n{}\n\n改动 Key 后重启栗栗才会完全生效哦~", dsh_note),
        )

    def _on_delete(self):
        """删除：清 config.yaml + dsh 凭据（二次确认）。"""
        # 二次确认（删除影响使用）
        r = QMessageBox.question(
            self, "栗栗",
            tr(
                "确定要删除 API Key 吗？\n\n删除后：\n"
                "　· 聊天退回模拟回复\n"
                "　· 干活会提示没有 Key\n\n"
                "不会出错崩溃，放心~"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return

        # 1. 清 config.yaml（闲聊）
        self._settings.deepseek_api_key = ""
        self._api_key_input.clear()
        self._update_status()

        # 2. 删 dsh 凭据（干活）
        dsh_note = ""
        if self._gateway is not None:
            try:
                self._gateway.rpc.credentials_unset("DEEPSEEK_API_KEY")
                dsh_note = tr("干活引擎里的 Key 也已删除。")
            except Exception:
                dsh_note = tr("干活引擎没连上，只删了聊天这份，等它启动后再删一次。")
        else:
            dsh_note = tr("干活引擎当前没启动，等它启动后再删一次。")

        QMessageBox.information(
            self, "栗栗",
            tr("Key 已删除。\n\n{}\n\n重启栗栗后完全生效。", dsh_note),
        )


# ============================================================
# 模块级测试（只验证 UI 能打开、能填/显/删，不真连引擎）
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    from tamias.settings import Settings

    app = QApplication(sys.argv)
    settings = Settings()
    # 传 gateway=None：模拟引擎没开，验证「只写 config.yaml」降级路径
    dlg = SettingsDialog(settings, gateway=None)
    print("设置对话框已打开（gateway=None，双写降级为只写 config.yaml）")
    dlg.exec()
    print(f"关闭后 config.yaml 里的 Key：{bool(settings.deepseek_api_key)}")
