# ============================================================
# 栗栗（Tamias）— 聊天界面专用控件
# ============================================================
# 从 chat_dialog.py 拆出来的三个独立小控件/工作器，只依赖 Qt 和 tr()，
# 不碰 ChatDialog 的内部状态，单独成文件方便复用（chat_dialog 太大，见文件放置准则）：
#   - ReplyWorker    后台线程工作器（延迟执行回调，不阻塞 UI）
#   - AnimatedButton 带 hover 平滑动画的按钮
#   - SlideStack     带翻页动画的页面容器（接口对齐 QStackedWidget 常用方法）
# ============================================================

from PySide6.QtWidgets import QPushButton, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy
from PySide6.QtCore import QObject, QTimer, Signal, Qt

from tamias.i18n import tr


class ReplyWorker(QObject):
    """后台工作器：延迟执行回调，不阻塞 UI 初始渲染。"""
    finished = Signal(str)   # 成功：callback 返回 (True, text)，发 text
    failed = Signal(str)     # 失败：callback 返回 (False, text) 或抛异常，发 text

    def __init__(self, callback, message, parent=None, conv_id=None, on_chunk=None, on_status=None, on_step=None, on_todo=None, on_usage=None):
        super().__init__(parent)
        self._callback = callback
        self._message = message
        self._cancelled = False
        self._conv_id = conv_id  # 当前对话 id：透传给 dsh 层做 session 记忆隔离（每个对话一份干活上下文）
        self._on_chunk = on_chunk  # 流式增量回调（传给 callback 做打字机）
        self._on_status = on_status  # 状态回调（传给 callback 显示「正在干嘛」）
        self._on_step = on_step  # 步骤回调（传给 callback 罗列干活过程）
        self._on_todo = on_todo  # 计划清单回调（传给 callback 渲染「计划卡」）
        self._on_usage = on_usage  # token 用量回调（传给 callback 累加显示）

    def start(self):
        QTimer.singleShot(100, self._run)

    def cancel(self):
        self._cancelled = True

    def _run(self):
        if self._cancelled:
            return
        import threading
        threading.Thread(target=self._run_in_thread, daemon=True).start()

    def _run_in_thread(self):
        try:
            result = self._callback(self._message, conv_id=self._conv_id,
                                    on_chunk=self._on_chunk,
                                    on_status=self._on_status, on_step=self._on_step,
                                    on_todo=self._on_todo,
                                    on_usage=self._on_usage)
            # callback 统一返回 (ok, text)：成功发 finished、失败发 failed，
            # 让 UI 能区分「干完」和「失败（超时/卡死/报错）」——失败停住排队、成功才继续。
            ok, reply = result
            if self._cancelled:
                return
            if ok:
                self.finished.emit(reply)
            else:
                self.failed.emit(reply)
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(tr("抱歉，出错了：{}", str(e)))


class AnimatedButton(QPushButton):
    """带平滑 hover 动画的按钮"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._offset = 0.0
        self._anim = None

    def enterEvent(self, e):
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        if self._anim: self._anim.stop()
        self._anim = QPropertyAnimation(self, b"_offset")
        self._anim.setDuration(200); self._anim.setStartValue(self._offset)
        self._anim.setEndValue(8.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._update_offset)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        if self._anim: self._anim.stop()
        self._anim = QPropertyAnimation(self, b"_offset")
        self._anim.setDuration(200); self._anim.setStartValue(self._offset)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._update_offset)
        self._anim.start()
        super().leaveEvent(e)

    def _update_offset(self, val):
        self._offset = val
        self.setStyleSheet(self._base_style.replace("{offset}", f"{int(val)}px"))

    def _get_offset(self): return self._offset
    def _set_offset(self, v): self._offset = v
    _offset_prop = property(_get_offset, _set_offset)


class SlideStack(QWidget):
    """带动画的页面容器，接口对齐 QStackedWidget 的常用方法。
    切页时旧页向左滑出、新页从右滑入，做出「翻页」的感觉。
    QStackedLayout 不支持两个页面同时显示，所以这里手动叠放页面、动画它们的 pos。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages = []        # 页面 widget 列表
        self._current = -1      # 当前页索引
        self._anim = None       # 进行中的切换动画

    def addWidget(self, w):
        """加一个页面；第一个加入的自动显示"""
        w.setParent(self)
        w.hide()
        self._pages.append(w)
        if self._current < 0:
            self._current = 0
            w.setGeometry(self.rect())
            w.show()
        return len(self._pages) - 1

    def currentIndex(self):
        return self._current

    def widget(self, index):
        if 0 <= index < len(self._pages):
            return self._pages[index]
        return None

    def currentWidget(self):
        return self.widget(self._current)

    def setCurrentIndex(self, index):
        """无动画硬切（兼容 QStackedWidget 语义）"""
        if not (0 <= index < len(self._pages)) or index == self._current:
            return
        old = self._pages[self._current]
        old.hide()
        self._current = index
        new = self._pages[index]
        new.setGeometry(self.rect())
        new.show()
        new.raise_()

    def slide_to(self, index):
        """翻页动画：前进（index 增大）旧页左滑、新页右入；后退（返回）旧页右滑、新页左入，方向相反。"""
        # 停掉上一个动画
        if self._anim is not None:
            try:
                self._anim.stop()
            except Exception:
                pass
            self._anim = None
        if index == self._current or not (0 <= index < len(self._pages)):
            self.setCurrentIndex(index)
            return

        from PySide6.QtCore import QPoint, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup

        old = self._pages[self._current]
        new = self._pages[index]
        w, h = self.width(), self.height()

        # 方向：前进（index 增大）新页从右来、旧页左滑出；
        #       后退（index 减小）新页从左来、旧页右滑出（跟前进相反，像翻回去）
        forward = index > self._current
        new_start_x = w if forward else -w   # 新页起始：前进在右侧外，后退在左侧外
        old_end_x = -w if forward else w     # 旧页终点：前进左滑出，后退右滑出

        old.setGeometry(0, 0, w, h)
        new.setGeometry(new_start_x, 0, w, h)
        old.show()
        new.show()
        new.raise_()

        old_anim = QPropertyAnimation(old, b"pos", self)
        old_anim.setDuration(260)
        old_anim.setStartValue(QPoint(0, 0))
        old_anim.setEndValue(QPoint(old_end_x, 0))
        old_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        new_anim = QPropertyAnimation(new, b"pos", self)
        new_anim.setDuration(260)
        new_anim.setStartValue(QPoint(new_start_x, 0))
        new_anim.setEndValue(QPoint(0, 0))
        new_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(old_anim)
        group.addAnimation(new_anim)

        # 切页在动画开始前就更新（避免动画期间误判）
        self._current = index

        def _finish():
            old.hide()
            new.setGeometry(self.rect())
            self._anim = None

        group.finished.connect(_finish)
        self._anim = group
        group.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 空闲时让当前页贴满容器（动画进行中不干预，交给 _finish 收尾）
        if self._current >= 0 and self._anim is None:
            self._pages[self._current].setGeometry(self.rect())


class PlanCard(QWidget):
    """计划卡：干活时把 todo 清单渲染成 ☐待做 / ⏳进行中 / ✅完成 的列表。
    挂在聊天流里，每次 todo/write 事件推一份完整清单就整体重绘（last-write-wins，
    无部分更新）。只用 Qt + tr()，不碰 ChatDialog 内部状态，符合本文件控件定位。"""

    # 状态 → 行首符号。三态一眼区分：待做 / 进行中 / 完成。
    _SYMBOL = {"pending": "☐", "in_progress": "⏳", "completed": "✅"}

    def __init__(self, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self._todos = []

        # 外层横向布局：卡片靠左，右侧留白（跟聊天气泡一致，不占满整行）
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 1, 0, 1)
        outer.setSpacing(0)
        self._box = QWidget()
        self._box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._box.setMaximumWidth(480)  # 跟聊天气泡宽度对齐，避免清单拉太宽
        outer.addWidget(self._box)
        outer.addStretch()

        self._lay = QVBoxLayout(self._box)
        self._lay.setContentsMargins(12, 8, 12, 8)
        self._lay.setSpacing(4)

        # 标题行：左「📋 计划」+ 右「已完成 N/M」
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._title = QLabel(tr("📋 计划"))
        title_row.addWidget(self._title)
        self._count = QLabel("")
        self._count.setVisible(False)
        title_row.addStretch()
        title_row.addWidget(self._count)
        self._lay.addLayout(title_row)

        # todo 行容器：每次 set_todos 整体重建（只动它，不碰标题行）
        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(3)
        self._lay.addLayout(self._rows_lay)

        self._apply_style()

    def _apply_style(self):
        """按主题上色：深色终端用浅字，暖棕气泡用深字。"""
        if self._dark:
            self._box.setStyleSheet("background:#111; border:1px solid #333; border-radius:10px;")
            self._title.setStyleSheet("color:#00FF66; font-weight:bold; font-size:11px;")
            self._count.setStyleSheet("color:#8A8A8A; font-size:10px;")
        else:
            self._box.setStyleSheet("background:#FFFDF7; border:1px solid #E4D3BC; border-radius:10px;")
            self._title.setStyleSheet("color:#A9745B; font-weight:bold; font-size:11px;")
            self._count.setStyleSheet("color:#8A7A6E; font-size:10px;")

    def _row_color(self, status: str) -> str:
        """每行文字颜色：完成绿、进行中暖黄、待做中性；深色终端整体提亮。"""
        return {
            "pending": "#8A8A8A" if self._dark else "#8A7A6E",
            "in_progress": "#E0B24C" if self._dark else "#C08A2D",
            "completed": "#3ECF7A" if self._dark else "#2E9E5B",
        }.get(status, "#8A8A8A" if self._dark else "#8A7A6E")

    def set_todos(self, todos: list):
        """整体重绘清单：清掉旧行，再按最新完整清单逐行渲染。
        todos 是 [{content, status}]，status ∈ pending / in_progress / completed；
        空列表则只显示标题（无行）。"""
        # 清空旧行（只清 _rows_lay，标题行不动）
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._todos = list(todos) if todos else []

        # 更新「已完成 N/M」计数
        done = sum(1 for t in self._todos if t.get("status") == "completed")
        total = len(self._todos)
        self._count.setText(tr("已完成 {}/{}", done, total) if total else "")
        self._count.setVisible(bool(total))

        # 逐行渲染
        for todo in self._todos:
            content = todo.get("content", "") if isinstance(todo, dict) else str(todo)
            status = todo.get("status", "pending") if isinstance(todo, dict) else "pending"
            sym = self._SYMBOL.get(status, "☐")
            color = self._row_color(status)

            row_widget = QWidget()
            hl = QHBoxLayout(row_widget)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            icon_lb = QLabel(sym)
            icon_lb.setFixedWidth(20)
            icon_lb.setStyleSheet(f"color:{color}; font-size:13px;")
            text_lb = QLabel(content)
            text_lb.setWordWrap(True)
            text_lb.setStyleSheet(f"color:{color}; font-size:12px;")
            text_lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            hl.addWidget(icon_lb, 0, Qt.AlignmentFlag.AlignTop)
            hl.addWidget(text_lb, 1)
            self._rows_lay.addWidget(row_widget)
