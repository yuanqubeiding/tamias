# ============================================================
# 栗栗（Tamias）— 人设资源加载器
# ============================================================
# 「皮骨分离」的「皮」。
#   人设（五锚 / 来源故事 / 口头禅）和口吻话术，不再硬编码进 main.py / gate.py，
#   而是放进 resources/persona/<名字>/ 下的 yaml 资源包，本模块统一读取。
#   换角色 = 换一个 persona 目录 + config.yaml 里改 persona 字段，代码一行不改。
# 「骨」（门禁判断逻辑 / 干活引擎 / 记忆隔离 / 审批回路）锁死，不随 persona 走。
# ============================================================

# 人设档案 01118Q6C05

from pathlib import Path
from typing import Dict

import yaml

# persona 资源根目录
PERSONA_DIR = Path(__file__).resolve().parent / "resources" / "persona"

# 默认 persona 名字（= 目录名）
DEFAULT_PERSONA = "tamias"

# 内置兜底话术：phrases.yaml 缺失或漏 key 时用，保证不崩、有话术。
# ⚠️ 中文原文 = i18n 翻译的 key，改文案需同步 en / ja / zh-TW 三个语言包。
_DEFAULT_PHRASES: Dict[str, str] = {
    # ---- 干活确认（gate.py 干活前）----
    "gate_task_confirm": (
        "栗栗检测到你想让我帮你干活呢！\n\n"
        "你的需求：{}\n\n"
        "这是需要调用AI编程助手的任务，可能涉及文件读写等操作。\n"
        "要继续吗？"
    ),
    "gate_task_title": "启动AI干活助手",
    "gate_task_rejected": "好的，栗栗不会执行这个任务呢~如果改变了主意，随时跟我说哦！",
    "gate_task_done": "任务完成啦！\n\n{}",
    "gate_task_error": "呜...执行任务时出错了：{}\n请检查栗栗的干活引擎是否正确配置哦~",
    "gate_task_no_engine": (
        "栗栗收到任务啦！你想让我：{}\n\n"
        "不过栗栗的干活引擎还没接好，暂时还不能帮你做呢~"
        "先跟我聊聊天吧！"
    ),
    # ---- 干活前门禁（main.py _gate_confirm）----
    "gate_confirm_task": (
        "栗栗收到一个干活任务：\n\n{}\n\n"
        "这可能涉及文件读写、执行命令等操作哦~\n"
        "要批准栗栗开始吗？"
    ),
    "gate_confirm_title": "栗栗要开始干活啦",
    # ---- 逐操作审批（main.py _approval_callback）----
    "approval_operation": (
        "栗栗想执行操作：{}\n\n"
        "{}\n\n"
        "批准后才会真正执行哦~"
    ),
    "approval_operation_short": "栗栗想执行操作：{}\n\n批准后才会真正执行哦~",
    "approval_title": "栗栗需要你的批准",
    # ---- 干活引擎状态（main.py dsh_handler / work_handler）----
    "engine_not_ready": "栗栗的 Harness 引擎还没连上呢~",
    "work_engine_not_ready": "栗栗的干活引擎还没连上呢，暂时帮不了这个忙哦~",
    "work_cancelled": "好的，栗栗没有动手哦~你想好了随时再叫栗栗！(◕‿◕)",
    "engine_error": "出错：{}",
    # ---- 聊天降级（main.py on_chat_message）----
    "chat_error": "呜...出错了呢：{}",
    "no_key_reply": (
        "栗栗收到啦～你说：{}\n\n"
        "💡 提示：配置 DeepSeek API Key 后栗栗就能跟你聊天了！\n"
        "   编辑 config.yaml 设置 deepseek.api_key 即可。\n\n"
        "不过如果你想让栗栗帮你干活（写代码/改文件等），\n"
        "直接说就行，栗栗会用 AI 引擎帮你哦～"
    ),
}


class Persona:
    """一个人设资源包：人设（persona.yaml）+ 口吻话术（phrases.yaml）。"""

    def __init__(self, name: str = DEFAULT_PERSONA):
        self.name = name
        self._dir = PERSONA_DIR / name
        self._persona: Dict[str, object] = {}
        self._phrases: Dict[str, str] = dict(_DEFAULT_PHRASES)  # 先内置兜底，再被 yaml 覆盖
        self._load()

    # ---------- 加载 ----------

    def _load(self) -> None:
        """加载 persona.yaml（人设）和 phrases.yaml（话术）；读坏不崩，用兜底。"""
        p_file = self._dir / "persona.yaml"
        if p_file.exists():
            try:
                self._persona = yaml.safe_load(p_file.read_text(encoding="utf-8")) or {}
            except Exception as e:
                print(f"[栗栗] 读取人设资源失败（{p_file}）：{e}")
        ph_file = self._dir / "phrases.yaml"
        if ph_file.exists():
            try:
                data = yaml.safe_load(ph_file.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    self._phrases.update(data)
            except Exception as e:
                print(f"[栗栗] 读取话术资源失败（{ph_file}）：{e}")

    # ---------- 人设 ----------

    def build_system_prompt(self, lang: str) -> str:
        """按当前界面语言拼 system prompt：人设五锚 + 语气 + 口头禅 + 来源故事 + 回复语言指令。"""
        # 人设资源缺失 → 回退旧版简短人设（保底，不崩）
        if not self._persona:
            return (
                "你是栗栗，一个住在用户电脑里的松鼠侦探管家。"
                "你说话风格活泼可爱，喜欢用'呢'、'哦'、'~'等语气词。"
                "你住在用户的桌面上，是用户的好朋友。"
                "回答要简洁，不要太长，保持轻松愉快的语气。"
                "称呼用户为'你'。"
                f"\n{self._lang_instruction(lang)}"
            )

        name = self._persona.get("name", "栗栗")
        name_en = self._persona.get("name_en", "") or ""
        one_line = self._persona.get("one_line", "")
        anchors = self._persona.get("anchors", {}) or {}
        appearance = self._persona.get("appearance", "")
        tone = self._persona.get("tone", {}) or {}
        catchphrases = self._persona.get("catchphrases", {}) or {}
        backstory = str(self._persona.get("backstory", "") or "").strip()

        # 非中文界面用英文名（Tamias），避免模型把中文名「栗栗」音译成拼音
        if name_en and lang not in ("zh-CN", "zh-TW"):
            lines = [f"Your name is {name_en}. Always refer to yourself as {name_en}."]
        else:
            lines = [f"你是{name}。"]
        if one_line:
            lines += ["", "【你是谁】", str(one_line)]
        if anchors:
            lines += ["", "【你的性格】"]
            for label, key in (
                ("身份", "identity"), ("性格", "personality"), ("反差", "contrast"),
                ("称呼", "catchphrase"), ("关系", "relationship"),
            ):
                val = anchors.get(key)
                if val:
                    lines.append(f"- {label}：{val}")
        if appearance:
            lines += ["", "【你的样子】", str(appearance)]
        if tone:
            lines += ["", "【你的说话分寸】"]
            for label, key in (("闲聊", "chat"), ("办事", "work"), ("忙时", "idle"), ("拦危险", "guard")):
                val = tone.get(key)
                if val:
                    lines.append(f"- {label}：{val}")
        if catchphrases:
            lines += ["", "【你的口头禅】"]
            for label, key in (("接任务", "take_task"), ("犯错", "make_mistake"),
                               ("拦危险", "block_danger"), ("被夸", "praised")):
                val = catchphrases.get(key)
                if val:
                    lines.append(f"- {label}：「{val}」")
        if backstory:
            lines += ["", "【你的故事】", backstory]
        lines += ["", "【回复要求】", "回答要简洁，不要太长，保持轻松愉快的语气。称呼用户为「你」。"]
        lang_instr = self._lang_instruction(lang)
        if lang_instr:
            lines.append(lang_instr)

        return "\n".join(lines)

    def _lang_instruction(self, lang: str) -> str:
        """取当前语言的回复语言指令（persona.yaml 里配，缺省回简体中文）。"""
        mapping = self._persona.get("lang_instructions", {}) or {}
        return mapping.get(lang) or mapping.get("_default") or "请始终用简体中文回复，不要夹杂其他语言。"

    # ---------- 口吻话术 ----------

    def phrase(self, key: str) -> str:
        """取口吻话术的中文原文模板（含 {} 占位符，交给 tr() 做 format 和翻译）。"""
        return self._phrases.get(key, "")


def list_personas() -> list:
    """
    扫描 persona 资源根目录，返回所有可用人设包的元信息列表。

    每个元素：
        {"dir": 目录名, "name": 显示名, "name_en": 英文名, "one_line": 一句话人设}
    目录里 persona.yaml 读坏的跳过、读不出的字段用目录名兜底；
    目录缺失或没有默认人设时，至少兜底返回 tamias（保证列表非空）。
    """
    result = []
    if PERSONA_DIR.exists():
        for sub in sorted(PERSONA_DIR.iterdir()):
            if not sub.is_dir():
                continue
            entry = {"dir": sub.name, "name": sub.name, "name_en": "", "one_line": ""}
            p_file = sub / "persona.yaml"
            if p_file.exists():
                try:
                    data = yaml.safe_load(p_file.read_text(encoding="utf-8")) or {}
                    if isinstance(data, dict):
                        entry["name"] = data.get("name", sub.name)
                        entry["name_en"] = data.get("name_en", "")
                        entry["one_line"] = data.get("one_line", "")
                except Exception as e:
                    print(f"[栗栗] 读取人设信息失败（{p_file}）：{e}")
            result.append(entry)

    # 兜底：目录不存在或列表里没有默认人设时，补一个 tamias
    if not any(e["dir"] == DEFAULT_PERSONA for e in result):
        result.insert(0, {"dir": DEFAULT_PERSONA, "name": "栗栗", "name_en": "", "one_line": ""})
    return result
