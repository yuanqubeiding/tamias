# ============================================================
# 栗栗（Tamias）— 多语言（i18n）模块
# ============================================================
# 用「中文原文当 key」的语言包：tr("发送") 从当前语言包查翻译，
# 找不到就原样返回中文（中文原文兜底），所以逐步替换零风险。
# 语言包放在 tamias/i18n/ 下，文件名 = 语言代码.json。
# ============================================================

import json
from pathlib import Path

# 语言包目录
I18N_DIR = Path(__file__).resolve().parent / "i18n"

# 支持的语言：代码 → 显示名（语言名用各自母语，切换界面里直接展示）
LANGUAGES = {
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "en": "English",
    "ja": "日本語",
}

_current_lang = "zh-CN"
_translations: dict = {}


def set_language(lang: str) -> None:
    """切换语言。启动时按配置调用一次；改语言需重启栗栗生效。"""
    global _current_lang, _translations
    if lang not in LANGUAGES:
        lang = "zh-CN"
    _current_lang = lang
    _translations = {}
    f = I18N_DIR / f"{lang}.json"
    if f.exists():
        try:
            _translations = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            # 语言包读坏（JSON 损坏）：退回空表，tr 会原样返回中文兜底
            _translations = {}


def tr(text: str, *args) -> str:
    """翻译一段文案；找不到翻译就原样返回（中文原文兜底）。
    支持占位符：tr("你好，{}", name) 会按语言包里的 {} 做格式化。"""
    s = _translations.get(text, text)
    if args:
        try:
            s = s.format(*args)
        except Exception:
            pass
    return s


def current_language() -> str:
    """当前语言代码"""
    return _current_lang
