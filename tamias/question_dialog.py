# ============================================================
# 栗栗（Tamias）— 二次元选择题弹窗（反问）
# ============================================================
# 当干活引擎（dsh）遇到歧义、反过来问主人「你到底指哪个」时弹出的窗口。
# 引擎会停下等回答，栗栗用这个窗口收集主人的选择，回传给引擎继续干活。
# 颜色用普通模式暖色系（跟聊天界面一致，临时配色，人设定稿后再统一）。
# ============================================================

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QButtonGroup, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from tamias.i18n import tr
from tamias.fonts import ui_font
from tamias.ui_icons import apply_icon


# ---------- 常量 ----------

DIALOG_WIDTH = 440
DIALOG_HEIGHT = 420

# 颜色主题（普通模式暖色系，跟 chat_dialog 聊天界面对齐；人设定稿后再统一）
COLOR_BG = "#F5EDE1"          # 背景（暖羊皮纸米白）
COLOR_BORDER = "#C7A27E"      # 边框（浅暖棕）
COLOR_APPROVE = "#A9745B"     # 确定按钮（栗棕/焦糖，栗栗主色）
COLOR_APPROVE_HOVER = "#8A5F49"   # 确定按钮 hover（深栗）
COLOR_APPROVE_PRESSED = "#6E4A38"  # 确定按钮 pressed（更深栗）
COLOR_SKIP_BG = "#FFFDF7"     # 跳过按钮背景（暖奶白）
COLOR_SKIP_TEXT = "#463329"   # 跳过按钮文字（深咖）
COLOR_SKIP_BORDER = "#C7A27E"  # 跳过按钮边框（浅暖棕）
COLOR_TITLE = "#7A5540"       # 标题（暖棕）
COLOR_PANEL = "#FFFDF7"       # 选项/输入框背景（暖奶白）
COLOR_TEXT = "#463329"        # 正文（深咖）
COLOR_TEXT_DIM = "#A98B6D"    # 次要文字（浅暖棕）


class QuestionDialog(QDialog):
    """
    二次元选择题弹窗
    -------------
    当引擎反问主人时弹出，展示一个/多个问题，收集主人的选择。

    使用方式：
        dialog = QuestionDialog(questions, parent=pet_window)
        dialog.exec()                    # 模态阻塞，等主人选完
        answers = dialog.get_answers()   # [{id, selected:[label], custom?}]

    questions 是 dsh 反问帧里的 AskUserQuestionItem 列表，每项：
        {id, question, header?, detail?, options:[{label,description?}], multiSelect?}
    """

    def __init__(self, questions: list, parent=None):
        """
        Args:
            questions: dsh 反问的问题列表（AskUserQuestionItem[]）
            parent: 父窗口
        """
        super().__init__(parent)

        self._questions = questions or []
        self._answer_rows = []  # 每个问题一行「怎么收集答案」的控件引用

        # ---------- 窗口设置 ----------
        self.setWindowTitle(tr("栗栗想确认一下"))
        self.setFixedSize(DIALOG_WIDTH, DIALOG_HEIGHT)

        # 非模态，不阻塞聊天窗口
        self.setWindowModality(Qt.WindowModality.NonModal)

        # 去掉问号按钮（setWindowFlag 精确关一个 flag，避免 &~ 在 PySide6 下误删 X 关闭按钮）
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        # 背景样式
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_BG};
                border: 2px solid {COLOR_BORDER};
                border-radius: 4px;
            }}
        """)

        # ---------- 构建 UI ----------
        self._init_ui()

        # ---------- 定位到父窗口附近 ----------
        self._position_near_parent()

    def _init_ui(self):
        """构建 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(10)

        # --- 标题 ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        title_label = QLabel(tr("栗栗想跟你确认一下～"))
        title_font = ui_font(13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {COLOR_TITLE};")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title_label, stretch=1)

        main_layout.addLayout(header_layout)

        # --- 分隔线 ---
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; border-radius: 1px;")
        main_layout.addWidget(sep)

        # --- 问题区（可滚动，放得下多个问题） ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: #C7A27E;
                border-radius: 3px;
            }}
        """)

        question_widget = QWidget()
        question_widget.setStyleSheet(f"background-color: {COLOR_BG};")
        q_layout = QVBoxLayout(question_widget)
        q_layout.setContentsMargins(0, 0, 0, 0)
        q_layout.setSpacing(14)

        # 逐个问题渲染
        for i, q in enumerate(self._questions):
            q_layout.addLayout(self._build_question(q, i))

        q_layout.addStretch(1)
        scroll.setWidget(question_widget)
        main_layout.addWidget(scroll, stretch=1)

        # --- 按钮区 ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)

        # 确定按钮
        ok_btn = apply_icon(QPushButton(), "circle-check", tr("✅  就这个啦"))
        ok_btn.setMinimumHeight(42)
        ok_font = ui_font(11)
        ok_font.setBold(True)
        ok_btn.setFont(ok_font)
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_APPROVE};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_APPROVE_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_APPROVE_PRESSED};
            }}
        """)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        # 跳过按钮（等同「不知道，你看着办」）
        skip_btn = QPushButton(tr("跳过"))
        skip_btn.setMinimumHeight(42)
        skip_font = ui_font(11)
        skip_btn.setFont(skip_font)
        skip_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SKIP_BG};
                color: {COLOR_SKIP_TEXT};
                border: 1px solid {COLOR_SKIP_BORDER};
                border-radius: 4px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: #F5EDE1;
            }}
            QPushButton:pressed {{
                background-color: #E4D3BC;
            }}
        """)
        skip_btn.clicked.connect(self.reject)
        button_layout.addWidget(skip_btn)

        main_layout.addLayout(button_layout)

    def _build_question(self, q: dict, index: int):
        """渲染一个问题：标题 + 问题文字 + 选项（单选/多选）或自由输入。"""
        layout = QVBoxLayout()
        layout.setSpacing(6)

        qid = q.get("id", f"q{index}")

        # 小标题（header，可选）
        header = q.get("header", "")
        if header:
            header_lb = QLabel(header)
            header_font = ui_font(9)
            header_font.setBold(True)
            header_lb.setFont(header_font)
            header_lb.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
            layout.addWidget(header_lb)

        # 问题正文
        question_text = q.get("question", "")
        if question_text:
            q_lb = QLabel(question_text)
            q_lb.setWordWrap(True)
            q_font = ui_font(10)
            q_lb.setFont(q_font)
            q_lb.setStyleSheet(f"color: {COLOR_TEXT};")
            layout.addWidget(q_lb)

        # 选项（options）或自由输入
        options = q.get("options", []) or []
        multi = bool(q.get("multiSelect", False))

        if options:
            # 有选项：单选用互斥按钮组，多选用独立勾选按钮
            # 末尾追加一个「其他（自己写）」按钮 + 隐藏输入框，让固定选项之外也能自定义
            row = {"id": qid, "kind": "multi" if multi else "single",
                   "buttons": [], "input": None, "other_btn": None, "other_input": None}
            btn_group = QButtonGroup(self)
            # 单选互斥、多选非互斥（QButtonGroup 默认互斥，多选必须显式关掉）
            btn_group.setExclusive(not multi)

            for opt in options:
                label = opt.get("label", "") if isinstance(opt, dict) else str(opt)
                desc = opt.get("description", "") if isinstance(opt, dict) else ""
                # 显示文字：label（+ 换行小字描述，如果有）
                btn_text = label
                if desc:
                    btn_text = f"{label}\n{desc}"

                btn = QPushButton(btn_text)
                btn.setCheckable(True)
                btn.setStyleSheet(self._option_style())
                btn.setMinimumHeight(36)
                if desc:
                    btn.setMinimumHeight(52)
                btn_group.addButton(btn)
                layout.addWidget(btn)
                row["buttons"].append((btn, label))

            # 「✍️ 其他（自己写）」：勾中后显示输入框，单选时跟固定选项互斥
            other_btn = apply_icon(QPushButton(), "pencil", tr("✍️ 其他（自己写）"))
            other_btn.setCheckable(True)
            other_btn.setStyleSheet(self._option_style())
            other_btn.setMinimumHeight(36)
            btn_group.addButton(other_btn)
            layout.addWidget(other_btn)

            other_input = QLineEdit()
            other_input.setPlaceholderText(tr("在这里写你的回答…"))
            other_input.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {COLOR_PANEL};
                    color: {COLOR_TEXT};
                    border: 1px solid {COLOR_BORDER};
                    border-radius: 4px;
                    padding: 8px;
                }}
                QLineEdit:focus {{
                    border-color: {COLOR_TITLE};
                }}
            """)
            other_input.setFont(ui_font(10))
            other_input.hide()
            layout.addWidget(other_input)
            other_btn.toggled.connect(
                lambda checked, inp=other_input: self._on_other_toggled(checked, inp)
            )

            row["other_btn"] = other_btn
            row["other_input"] = other_input
            self._answer_rows.append(row)

        else:
            # 没选项：自由输入框
            row = {"id": qid, "kind": "free", "buttons": [], "input": None}
            line = QLineEdit()
            line.setPlaceholderText(tr("在这里写你的回答…"))
            line.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {COLOR_PANEL};
                    color: {COLOR_TEXT};
                    border: 1px solid {COLOR_BORDER};
                    border-radius: 4px;
                    padding: 8px;
                }}
                QLineEdit:focus {{
                    border-color: {COLOR_TITLE};
                }}
            """)
            line.setFont(ui_font(10))
            layout.addWidget(line)
            row["input"] = line
            self._answer_rows.append(row)

        return layout

    def _option_style(self) -> str:
        """选项按钮的样式（可勾选，勾中高亮）。"""
        return f"""
            QPushButton {{
                background-color: {COLOR_PANEL};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {COLOR_TITLE};
            }}
            QPushButton:checked {{
                background-color: {COLOR_APPROVE};
                color: white;
                border-color: {COLOR_APPROVE_HOVER};
            }}
        """

    def _on_other_toggled(self, checked: bool, input_box):
        """「其他」按钮勾选状态变化：勾中显示输入框并聚焦，取消则隐藏清空。"""
        if checked:
            input_box.show()
            input_box.setFocus()
        else:
            input_box.hide()
            input_box.clear()

    def get_answers(self) -> list:
        """收集主人的回答，返回结构化答案列表 [{id, selected, custom?}]。"""
        answers = []
        for row in self._answer_rows:
            item = {"id": row["id"]}
            if row["kind"] == "free":
                # 自由输入：文字放进 custom，selected 留空
                text = (row["input"].text() if row["input"] is not None else "").strip()
                item["selected"] = []
                if text:
                    item["custom"] = text
            else:
                # 单选/多选：收集勾中按钮的 label
                selected = [label for (btn, label) in row["buttons"] if btn.isChecked()]
                item["selected"] = selected
                # 勾了「其他」→ 把输入框文字放进 custom（selected 不含「其他」这个伪选项）
                if row.get("other_btn") and row["other_btn"].isChecked():
                    custom = (row["other_input"].text() if row["other_input"] is not None else "").strip()
                    if custom:
                        item["custom"] = custom
            answers.append(item)
        return answers

    def _position_near_parent(self):
        """定位到父窗口附近（跟确认弹窗一致）。"""
        parent = self.parent()
        if parent is None:
            return

        parent_geo = parent.frameGeometry()

        from PySide6.QtWidgets import QApplication
        screen = QApplication.screenAt(parent_geo.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        screen_geo = screen.availableGeometry()

        x = parent_geo.left() - DIALOG_WIDTH - 20
        if x < screen_geo.left():
            x = parent_geo.right() + 20
            if x + DIALOG_WIDTH > screen_geo.right():
                x = screen_geo.center().x() - DIALOG_WIDTH // 2

        y = parent_geo.top() - 50
        if y < screen_geo.top():
            y = screen_geo.top() + 20
        if y + DIALOG_HEIGHT > screen_geo.bottom():
            y = screen_geo.bottom() - DIALOG_HEIGHT - 20

        self.move(int(x), int(y))


# ============================================================
# 便捷函数：在其他模块中快速调用选择题弹窗
# ============================================================

def ask_questions(questions: list, parent=None) -> list:
    """
    显示选择题弹窗并返回主人的答案列表。

    Args:
        questions: dsh 反问的问题列表（AskUserQuestionItem[]）
        parent: 父窗口

    Returns:
        list: [{id, selected:[label], custom?}]；主人跳过/关窗则返回空选择
    """
    dialog = QuestionDialog(questions, parent=parent)
    dialog.exec()
    return dialog.get_answers()


# ============================================================
# 模块级测试
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    print("测试选择题弹窗...")

    test_questions = [
        {
            "id": "openedge_intent",
            "question": "What would you like to know or do about \"openedge\"?",
            "header": "Clarify",
            "options": [
                {"label": "Progress OpenEdge (ABL)", "description": "The development platform"},
                {"label": "Open the Edge browser", "description": "Launch Microsoft Edge"},
                {"label": "Just a casual mention", "description": "Not asking for anything"},
            ],
            "multiSelect": False,
        },
    ]

    answers = ask_questions(test_questions)
    print(f"主人的回答：{answers}")

    print("测试完成！")
