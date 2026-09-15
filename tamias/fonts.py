# ============================================================
# 栗栗（Tamias）— 界面字体加载器
# ============================================================
# 统一管理「中文 / 英文 / 日文」三语 + 等宽字体的加载与工厂函数。
#
# 字体选型（均为免费商用，随软件分发；授权文件见 resources/fonts/ 下 *.txt）：
#   - 中文 / 英文 UI：HarmonyOS Sans SC（鸿蒙字体，© Huawei Device Co., Ltd.）
#   - 日文：Noto Sans JP（思源黑体日文，Adobe/Google，SIL OFL 1.1）
#   - 等宽（代码 / 日志 / 终端）：JetBrains Mono（JetBrains，SIL OFL 1.1）
#
# 合规铁律（务必遵守，别改别裁）：
#   1. 鸿蒙字体：随软件「原样」分发、禁止修改；需在软件内「显著声明」
#      （见设置对话框关于页 / NOTICE.txt）；保留 HarmonyOS_Sans_LICENSE.txt。
#   2. Noto Sans JP / JetBrains Mono：SIL OFL 1.1，随附各自 OFL.txt 即可。
#
# 为什么「日文」用「按界面语言切全局字体」而不是字符级 fallback：
#   鸿蒙 SC 自带日文假名字形（实测 あ/ア/り/な 都 inFont=True），
#   Qt 的字符级回退会直接拿鸿蒙渲染假名、不会切到 Noto Sans JP。
#   所以改用「日语界面 → 全局 Noto Sans JP；中英界面 → 全局鸿蒙」，
#   正好贴合栗栗 i18n 的整界面语言切换结构，简单且彻底。
#
# 用法：
#   - main.py 启动最早处：install_fonts() + apply_app_font(settings.language)
#   - 各控件：ui_font(size, bold) / mono_font(size, bold) 替代硬编码 QFont
# ============================================================

import os
import sys

from PySide6.QtGui import QFont, QFontDatabase


# 字体文件所在目录：兼容「源码运行」与「PyInstaller 打包」两种场景
def _fonts_dir() -> str:
    # 打包后 PyInstaller 会把 datas 解到 sys._MEIPASS 下
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, "tamias", "resources", "fonts")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "fonts")


# 注册后的真实 family name（由字体内部元数据决定，非文件名）
FAMILY_HARMONY = "HarmonyOS Sans SC"   # 中文 / 英文
FAMILY_JP = "Noto Sans JP"             # 日文
FAMILY_MONO = "JetBrains Mono"         # 等宽

# 回退字体：万一注册失败（文件缺失），退回系统字体，保证界面不崩
_FALLBACK_UI = "Microsoft YaHei"
_FALLBACK_JP = "Yu Gothic UI"
_FALLBACK_MONO = "Consolas"


# 注册状态：{family_name: bool}，bool 表示是否注册成功
_registered = {}

# 当前界面语言（apply_app_font 设置）。ui_font 据此决定用鸿蒙还是思源：
# 日语界面需要「全站思源黑体 JP」，而所有控件都统一调 ui_font，
# 所以在这里分流，而不是让每个调用点自己去判断语言（那样必漏）。
_current_language: str | None = None

# 界面字号整体微调（单位 pt）：鸿蒙/思源在小字号下比微软雅黑略「糊」
# （微软雅黑针对 Windows ClearType 做了大量 hinting 优化，鸿蒙 hinting 较弱），
# 统一 +1 提升清晰度。等宽 JetBrains Mono 保持原样（代码/日志场景不糊）。
_SIZE_OFFSET = 1

# 繁体界面额外微调（单位 pt）：繁体字笔画比简体密，同样字号视觉上偏小偏挤，
# zh-TW 界面在全局 +1 基础上再 +2（共 +3），让繁体看起来和简体一样舒展清晰。
_TW_EXTRA_OFFSET = 2


def install_fonts() -> dict:
    """注册所有打包字体到 Qt 字体库（幂等，重复调用只做一次）。

    返回 {family_name: 是否成功}，供 apply_app_font / 工厂函数判断回退。
    """
    global _registered
    if _registered:
        return _registered

    d = _fonts_dir()
    # family -> 该字体需要注册的文件（Regular + Bold 共享同一 family）
    targets = {
        FAMILY_HARMONY: ["HarmonyOS_Sans_SC_Regular.ttf", "HarmonyOS_Sans_SC_Bold.ttf"],
        FAMILY_JP: ["NotoSansJP-Regular.otf", "NotoSansJP-Bold.otf"],
        FAMILY_MONO: ["JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"],
    }

    for family, filenames in targets.items():
        ok = False
        for fn in filenames:
            path = os.path.join(d, fn)
            if not os.path.exists(path):
                continue
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                ok = True  # 只要有一个字重注册成功，该字体就算可用
        _registered[family] = ok

    return _registered


def _family(family: str, fallback: str) -> str:
    """取注册成功的 family，否则退回系统字体。"""
    install_fonts()
    if _registered.get(family):
        return family
    return fallback


def ui_font(size: int, bold: bool = False) -> QFont:
    """中文 / 英文 UI 字体（鸿蒙）。日语界面返回思源黑体 JP，繁体界面额外 +1。

    为什么在这里分流：所有控件都统一调 ui_font，而日语界面要求「全站思源」、
    繁体字笔画密需要更大字号，让 ui_font 感知当前语言最省事、也不会漏掉调用点。
    """
    if _current_language == "ja":
        return jp_font(size, bold)
    extra = _TW_EXTRA_OFFSET if _current_language == "zh-TW" else 0
    f = QFont(_family(FAMILY_HARMONY, _FALLBACK_UI), size + _SIZE_OFFSET + extra)
    f.setBold(bold)
    return f


def jp_font(size: int, bold: bool = False) -> QFont:
    """日文字体（思源黑体 JP）。用于日语界面等需要日文字形的场景。"""
    f = QFont(_family(FAMILY_JP, _FALLBACK_JP), size + _SIZE_OFFSET)
    f.setBold(bold)
    return f


def mono_font(size: int, bold: bool = False) -> QFont:
    """等宽字体（JetBrains Mono，代码 / 日志 / 终端）。替代原来的 QFont("Consolas", size)。"""
    f = QFont(_family(FAMILY_MONO, _FALLBACK_MONO), size)
    f.setBold(bold)
    return f


def apply_app_font(language: str | None = None):
    """设置全局应用默认字体，跟随界面语言。

    - 日语界面（ja）：全局用 Noto Sans JP（正宗日文字形）
    - 中文 / 英文界面：全局用鸿蒙（HarmonyOS Sans SC）

    只影响「没有显式 setFont」的控件；显式 setFont 的控件由 ui_font / mono_font 接管。
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return

    global _current_language
    _current_language = language

    if language == "ja":
        app.setFont(jp_font(10))
    else:
        app.setFont(ui_font(10))
