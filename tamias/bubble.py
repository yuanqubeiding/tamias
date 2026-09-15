# ============================================================
# 栗栗（Tamias）— 漫画式对话气泡
# ============================================================
# 启动时 / 左键点击栗栗时，在皮套「头顶上方、整体偏左」弹一个漫画式
# 对话气泡，随机挑一句贴合「松鼠侦探管家」人设的话，几秒后自动淡出。
#
# 台词是「固定话术库」：中文原文当 i18n 的 key，tr() 按当前界面
# 语言翻译（找不到就原样返回中文兜底），所以四语言都能跟。
#
# 实现要点（踩过坑）：
#   - 文字直接在 paintEvent 里画，不用 QLabel 子控件；否则叠加
#     QGraphicsOpacityEffect 时，透明窗口的子控件文字会被渲染丢掉
#     （气泡背景能看到、字看不到）。
#   - 淡入淡出用 windowOpacity 动画，不用 QGraphicsOpacityEffect。
# ============================================================

import random

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPointF, QRectF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QFontMetrics, QPolygonF

from tamias.i18n import tr
from tamias.fonts import ui_font


# ---------- 话术库（中文原文 = i18n key） ----------

# 启动问候：栗栗「上线」时随机说一句
GREETINGS = [
    "栗栗来啦~今天也要好好当管家哦！",
    "嘿嘿，栗栗上线啦！",
    "早上好呀，有什么栗栗能帮忙的吗？",
    "栗栗报到！随时可以开工~",
    "哇，又见到你啦，栗栗好开心！",
    "今天也要一起加油哦~",
    "（伸个懒腰）栗栗准备好啦！",
]

# 被戳（左键点击）时随机说一句
POKED = [
    "嗯？怎么啦？",
    "嘿嘿，别戳栗栗啦~",
    "栗栗在哦！",
    "（尾巴抖了抖）什、什么事？",
    "有案子要交给栗栗吗？",
    "诶？被发现了！",
    "栗栗去查查~",
    "怎么啦？是不是要栗栗帮忙？",
]

# 被连续狂点（5 连击）惹生气时随机说一句
ANGRY = [
    "呜……你再戳，栗栗要生气啦！",
    "栗栗真的要生气啦！",
    "（气鼓鼓）不许再戳了啦！",
    "再戳栗栗就……就翻脸啦！",
    "哼！栗栗生气了哦！",
]

# 打哈欠（空闲触发）时随机说一句
YAWN = [
    "哈啊……有点困了呢。",
    "（打了个哈欠）栗栗眯一小会儿……",
    "呼啊……眼皮好重……",
    "好困哦……",
]

# 看书（空闲触发）时随机说一句
READING = [
    "（翻书）让栗栗看看……",
    "这本书好有意思。",
    "（翻书）原来是这样呀……",
    "栗栗充电中，知识就是力量！",
]

# 被长时间按住手（害羞慌张）时随机说一句
HAND_TOUCH = [
    "你、你抓着栗栗的手干嘛啦……",
    "（脸红）诶？手被抓住了……",
    "还、还不松手吗……",
    "干嘛啦……别一直抓着栗栗……",
]

# 深夜犯困（精神值 SAN 掉到低位触发）时随机说一句
NIGHT_SLEEPY = [
    "呜……好困……但主人还在，栗栗不能睡……",
    "（揉眼睛）哈啊……都这么晚了你还不休息吗……",
    "栗栗眼皮都要打架了……可是得陪你……（委屈）",
    "好想钻进窝里睡觉……可、可是要守着主人……",
]


def pick(kind: str) -> str:
    """从指定话术库里随机挑一句，并翻译成当前界面语言。"""
    pool = {
        "greeting": GREETINGS,
        "poked": POKED,
        "angry": ANGRY,
        "yawn": YAWN,
        "reading": READING,
        "hand_touch": HAND_TOUCH,
        "night_sleepy": NIGHT_SLEEPY,
    }.get(kind, POKED)
    return tr(random.choice(pool))


class BubbleWidget(QWidget):
    """漫画式对话气泡：圆角气泡 + 朝下的小尾巴，文字几秒后自动淡出。

    独立顶级窗口（会伸出皮套 200px 范围外，不能被父窗口裁掉），
    透明无边框、置顶、不抢焦点、鼠标穿透。
    """

    BG = QColor("#FFF9F0")      # 米白底
    BORDER = QColor("#C7A27E")  # 暖棕描边
    TEXT = QColor("#463329")    # 深棕文字
    RADIUS = 12                 # 圆角半径
    TAIL_W = 18                 # 尾巴宽（底部，左右）
    TAIL_H = 14                 # 尾巴高（朝下伸出）

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._text = ""
        self._body_w = 100  # 气泡身体宽（_resize_for_text 里重算）
        self._body_h = 40   # 气泡身体高

        # 淡入/淡出：动画窗口透明度（透明无边框窗口也能用，见文件头注释）
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.finished.connect(self._on_anim_finished)

        # 自动消失定时器
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self.hide()

    # ---------- 对外 ----------

    def show_text(self, text: str, pet_rect, stay_ms: int = 3500):
        """在皮套（pet_rect = 其 frameGeometry）头顶上方偏左显示一句台词，stay_ms 后淡出。"""
        self._resize_for_text(text)
        self._position_at(pet_rect)

        self._hide_timer.stop()
        self._anim.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade_in(stay_ms)

    def show_status(self, text: str, pet_rect):
        """持续显示状态文字（正在思考/搜索…）：不自动淡出、文字变了原地更新不重闪。
        结束由调用方 hide_status() 触发淡出。"""
        self._resize_for_text(text)
        self._position_at(pet_rect)
        self._hide_timer.stop()   # 状态持续，不设自动消失
        self._anim.stop()
        self.setWindowOpacity(1.0)  # 直接全显（状态切换频繁，淡入会闪）
        self.show()
        self.raise_()

    def hide_status(self):
        """状态结束：立即淡出隐藏。"""
        self._hide_timer.stop()
        self._fade_out()

    def move_with(self, pet_rect):
        """皮套被拖动时，气泡跟随移动到新的头顶上方位置（不重置文字、不重启动画）。"""
        if self.isVisible():
            self._position_at(pet_rect)

    # ---------- 内部 ----------

    def _resize_for_text(self, text: str):
        """按文字长度自适应气泡大小（设最大宽度，超长自动换行）。"""
        self._text = text
        font = ui_font(11)
        fm = QFontMetrics(font)
        max_w = 200
        pad_x, pad_y = 16, 12

        line_w = fm.horizontalAdvance(text)
        if line_w <= max_w:
            # 单行：气泡贴着文字
            text_w = line_w + 4
            text_h = fm.height()
        else:
            # 超长：宽度封顶 + 换行
            text_w = max_w
            text_h = fm.boundingRect(0, 0, max_w, 0, Qt.TextFlag.TextWordWrap, text).height()

        self._body_w = text_w + pad_x * 2
        self._body_h = text_h + pad_y * 2
        # 宽 = 身体宽（尾巴在底部中央，不额外占宽）；高 = 身体 + 尾巴
        self.setFixedSize(self._body_w, self._body_h + self.TAIL_H)

    def _position_at(self, pet_rect):
        """把气泡放到皮套头顶上方、整体偏左；尾巴在底部朝下指向皮套。"""
        head_x = pet_rect.x() + pet_rect.width() / 2
        pet_top = pet_rect.y()
        x = head_x - self._body_w / 2 - 30   # 中心偏左 30px
        y = pet_top - self._body_h - self.TAIL_H - 10  # 皮套顶上方，留尾巴 + 间距
        x = max(int(x), 4)
        y = max(int(y), 4)
        self.move(int(x), int(y))

    def _fade_in(self, stay_ms: int):
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._hide_timer.start(stay_ms)

    def _fade_out(self):
        self._anim.setDuration(260)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self):
        # 淡出结束（透明度归零）才真正隐藏；淡入结束不用管
        if self.windowOpacity() <= 0.01:
            self.hide()

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 1. 气泡身体：圆角矩形 + 暖棕描边
        painter.setBrush(self.BG)
        painter.setPen(QPen(self.BORDER, 1.5))
        painter.drawRoundedRect(0, 0, self._body_w, self._body_h, self.RADIUS, self.RADIUS)

        # 2. 小尾巴：底部中央朝下的实心三角，盖住身体下缘中段，和身体连成一体
        tail_x = self._body_w / 2
        tail = QPolygonF([
            QPointF(tail_x - self.TAIL_W / 2, self._body_h - 2),
            QPointF(tail_x + self.TAIL_W / 2, self._body_h - 2),
            QPointF(tail_x, self._body_h + self.TAIL_H),
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(tail)

        # 3. 文字：直接画（居中 + 自动换行），不依赖子控件
        painter.setPen(self.TEXT)
        painter.setFont(ui_font(11))
        text_rect = QRectF(16, 12, self._body_w - 32, self._body_h - 24)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)
