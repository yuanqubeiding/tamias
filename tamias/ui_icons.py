# ============================================================
# 栗栗（Tamias）— 界面图标注册表（Lucide）
# ============================================================
# 统一管理界面小图标：把 Lucide 的 SVG 换成「跟随主题颜色」的 QIcon。
# 原来界面上的小图标是 emoji 字符（📁⚙️🔍…），全世界通用、太大众；
# 换成 Lucide 单色线条风，风格统一、有辨识度。
#
# 授权：Lucide 为 ISC 许可（免费商用、无需署名）。许可证随包放在
# resources/icons/lucide-LICENSE.txt，并在 NOTICE.txt 里声明。
#
# 为什么用「SVG + QSvgRenderer 运行时上色」而不是直接 QIcon(svg)：
# Lucide 的 SVG 里 stroke="currentColor"，Qt 的 SVG 渲染器不认识
# currentColor，会画成黑色；这里把 currentColor 换成具体色值，
# 让图标跟随深色/暖棕主题。
# ============================================================

import os
import re
import sys

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer


# 图标文件目录（兼容「源码运行」与「PyInstaller 打包」，思路同 fonts.py）
def _icons_dir() -> str:
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, "tamias", "resources", "icons")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons")


# 主题深浅：dark=True 用浅色笔画（深色背景），False 用深色笔画（浅色/暖棕背景）。
# 默认 False：菜单 / 功能库 / 欢迎卡这些都在普通模式（暖棕浅色）下显示。
_dark = False

# 笔画颜色（随主题切换）
_DARK_STROKE = "#cfd3d8"    # 深色主题：浅灰线条
_LIGHT_STROKE = "#555a60"   # 暖棕 / 浅色主题：深灰线条

# 行首 emoji 剥离正则（只在 apply_icon 里用，去掉「📁 文件」里的「📁」）。
# 只匹配行首 + 后随空白；中间/尾部的 emoji（天气🌤️、掷骰🎲 等）是内容，不动。
_EMOJI_LEAD = re.compile(
    r"^[\s]*[\U0001F000-\U0001FAFF☀-➿⬀-⯿"
    r"←-⇿️⏰-⏿▶⚔-⚡✅✍✏"
    r"✓-✗❌]+[\s]*"
)

_cache: dict = {}


def set_dark(dark: bool) -> None:
    """切换图标深浅（供主题应用时调用）。缓存按 (名字, 尺寸, 深浅) 存，切主题后新取会重建。"""
    global _dark
    _dark = bool(dark)


def strip_leading_emoji(text: str) -> str:
    """去掉行首的 emoji 图标 + 空白。中间/尾部的 emoji 不动（那是内容）。"""
    return _EMOJI_LEAD.sub("", text, count=1)


def _svg_text(name: str):
    f = os.path.join(_icons_dir(), f"{name}.svg")
    try:
        return open(f, encoding="utf-8").read()
    except OSError:
        return None


def icon(name: str, size: int = 18, dark: bool | None = None) -> QIcon:
    """返回指定图标（主题感知、按需缓存）。缺图标 → 空 QIcon，不崩。"""
    if dark is None:
        dark = _dark
    key = (name, size, dark)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    svg = _svg_text(name)
    if svg is None:
        empty = QIcon()
        _cache[key] = empty
        return empty

    color = _DARK_STROKE if dark else _LIGHT_STROKE
    svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    # 直接按逻辑尺寸画，不玩 2x/DPR 那套。
    # 2x+DPR 会让 QIcon.availableSizes() 报物理尺寸（如 size=16 报 32），
    # 高 DPI 屏上控件照着物理尺寸放大后图标被裁掉一角（用户看到「只露出一点点」）。
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0.0, 0.0, float(size), float(size)))
    p.end()

    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def apply_icon(widget, name: str, text: str, size: int = 18, dark: bool | None = None):
    """给按钮/复选/动作类控件：去掉行首 emoji + 设置主题图标。

    widget 需要有 setText + setIcon（QPushButton / QCheckBox / QAction / QToolButton 都满足）。
    返回 widget，方便链式写法。
    """
    widget.setText(strip_leading_emoji(text))
    ic = icon(name, size, dark)
    if not ic.isNull():
        widget.setIcon(ic)
    return widget


def draw_chestnut(painter: QPainter, cx: float, cy: float, r: float) -> None:
    """在 (cx, cy) 画一颗半径 r 的栗子：暖棕渐变主体 + 底部小尖 + 顶部小蒂 + 高光。

    用途：真图标 PNG / Live2D 模型缺失时的兜底占位（托盘图标、欢迎头像、桌面宠物）。
    不画人脸——代码手绘二次元脸必然粗糙，画栗子没有五官可丑，还贴「栗栗」这个名字。
    """
    # 主体：暖棕径向渐变（左上亮 → 右下暗），呼应主题暖棕色
    grad = QRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 1.6)
    grad.setColorAt(0.0, QColor(175, 125, 78))
    grad.setColorAt(0.55, QColor(130, 85, 48))
    grad.setColorAt(1.0, QColor(92, 58, 32))
    painter.setBrush(QBrush(grad))
    painter.setPen(QPen(QColor(70, 44, 25), max(1.2, r * 0.07)))
    # 栗子主体路径：顶部略平、两侧鼓、底部收成小尖
    body = QPainterPath()
    body.moveTo(cx - r * 0.85, cy - r * 0.55)                       # 顶部左
    body.quadTo(cx - r * 1.0, cy, cx - r * 0.35, cy + r * 0.55)     # 左弧
    body.quadTo(cx, cy + r * 1.05, cx + r * 0.35, cy + r * 0.55)    # 底部小尖
    body.quadTo(cx + r * 1.0, cy, cx + r * 0.85, cy - r * 0.55)     # 右弧
    body.quadTo(cx, cy - r * 0.75, cx - r * 0.85, cy - r * 0.55)    # 顶部弧（略平）
    body.closeSubpath()
    painter.drawPath(body)
    # 顶部小蒂
    painter.setBrush(QBrush(QColor(70, 45, 25)))
    painter.setPen(Qt.PenStyle.NoPen)
    stem = QPainterPath()
    stem.moveTo(cx - r * 0.22, cy - r * 0.55)
    stem.quadTo(cx, cy - r * 0.9, cx + r * 0.22, cy - r * 0.55)
    stem.closeSubpath()
    painter.drawPath(stem)
    # 高光（左上一点反光，让栗子不呆板）
    painter.setBrush(QBrush(QColor(255, 240, 210, 120)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(cx - r * 0.4, cy - r * 0.35), r * 0.22, r * 0.14)
