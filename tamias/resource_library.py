# ============================================================
# 栗栗（Tamias）— 资源库对话框
# ============================================================
# 展示 resources/persona/ 下的所有人设包，用户点选即可切换角色。
# 换角色 = 改 config.yaml 的 persona 字段 + 重启栗栗，代码一行不动。
# 皮肤库（立绘/模型/差分）后续会并进这里，眼下先只做「人设包」这一层。
# ============================================================

import os
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from tamias.i18n import tr
from tamias.fonts import ui_font
from tamias.ui_icons import apply_icon, strip_leading_emoji
from tamias.persona import list_personas, PERSONA_DIR, DEFAULT_PERSONA


class ResourceLibrary(QDialog):
    """
    栗栗资源库。
    -----------
    列出所有人设包，点选即切换当前角色（写 config.yaml 的 persona 字段）。
    """

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        # 当前使用中的人设包名（= 目录名）
        self._current = settings.persona if settings else DEFAULT_PERSONA

        self.setWindowTitle(tr("栗栗 - 资源库"))
        self.setMinimumSize(420, 360)
        self.setModal(True)
        # 暖棕侦探风背景，跟设置对话框/聊天普通模式统一
        self.setStyleSheet("QDialog { background: #F5EDE1; }")

        self._build_ui()
        self._reload()

    # ---------- 界面搭建 ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel(strip_leading_emoji(tr("🎨 资源库")))
        title.setFont(ui_font(14, bold=True))
        title.setStyleSheet("color: #7A5540;")
        layout.addWidget(title)

        # 说明
        desc = QLabel(tr("这里是栗栗的「皮」——人设和皮肤。点选即切换，重启栗栗后生效。"))
        desc.setWordWrap(True)
        desc.setFont(ui_font(10))
        desc.setStyleSheet("color: #463329;")
        layout.addWidget(desc)

        # 人设列表
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setFont(ui_font(11))
        self._list.setStyleSheet(
            "QListWidget { background: #FFFFFF; color: #463329; border: 2px solid #C7A27E; "
            "border-radius: 8px; padding: 4px; }"
            "QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #F0E4D2; }"
            "QListWidget::item:selected { background: #EDE0CC; color: #463329; }"
        )
        self._list.itemClicked.connect(self._on_select)
        layout.addWidget(self._list, 1)

        # 状态提示
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setFont(ui_font(9))
        self._hint.setStyleSheet("color: #B07B50;")
        layout.addWidget(self._hint)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        open_btn = apply_icon(QPushButton(), "folder-open", tr("📂 打开人设文件夹"))
        open_btn.setStyleSheet(self._btn_style())
        open_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(open_btn)

        btn_row.addStretch()

        close_btn = QPushButton(tr("关闭"))
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(self._primary_btn_style())
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    # ---------- 数据 ----------

    def _reload(self):
        """重载人设列表，标记当前使用中的角色。"""
        self._list.clear()
        for p in list_personas():
            label = p["name"]
            if p.get("one_line"):
                label += f" — {p['one_line']}"
            if p["dir"] == self._current:
                label += tr("　（使用中）")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p["dir"])
            if p["dir"] == self._current:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self._list.addItem(item)

    def _on_select(self, item):
        """点选某个人设 → 写入 config.yaml 的 persona 字段。"""
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name or name == self._current:
            return
        if self._settings:
            self._settings.set("persona", name)
        self._current = name
        self._hint.setText(tr("已选择「{}」。重启栗栗后生效哦~", name))
        self._reload()

    def _on_open_folder(self):
        """用系统资源管理器打开人设文件夹，方便用户手动放新皮。"""
        try:
            os.startfile(str(PERSONA_DIR))
        except Exception as e:
            QMessageBox.warning(self, "栗栗", tr("打开文件夹失败：{}", e))

    # ---------- 样式 ----------

    @staticmethod
    def _btn_style():
        return """
            QPushButton {
                background-color: transparent;
                color: #7A5540;
                border: 1px solid #C7A27E;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #EDE0CC; }
        """

    @staticmethod
    def _primary_btn_style():
        return """
            QPushButton {
                background-color: #A9745B;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #9A6550; }
        """


# ============================================================
# 模块级测试（只验证 UI 能打开、能列人设、能点选切换）
# ============================================================
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from tamias.settings import Settings

    app = QApplication(sys.argv)
    settings = Settings()
    dlg = ResourceLibrary(settings)
    print("资源库对话框已打开")
    dlg.exec()
    print(f"关闭后当前 persona：{settings.persona}")
