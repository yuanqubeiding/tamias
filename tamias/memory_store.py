# ============================================================
# 栗栗（Tamias）— 长期记忆存储（基于 dsh 内置 skill 系统）
# ============================================================
# 栗栗的长期记忆 = 一条事实一个 SKILL.md，放在 dsh 的 skill 扫描目录里。
#
# 原理：dsh 的 standard preset 已挂 dsh-skill-filesystem，会自动扫描
#   <DSH_HOME>/skills 下的 SKILL.md，把每条记忆的 name+description 注入
#   会话（skill catalog，等价于 Claude Code 的 MEMORY.md 索引），干活时
#   按需用 skill 工具加载正文 —— 与 Claude 的「索引自动加载 + 文件按需读」同构。
#
# 存放位置（两级，对齐 Claude Code 的「全局 + 项目」分层）：
#   全局记忆：%APPDATA%\Tamias\dsh\skills\<slug>\SKILL.md  （用户级，哪都生效）
#   项目记忆：<工作目录>\.dsh\skills\<slug>\SKILL.md        （项目级，只在该目录干活时生效）
#   DSH_HOME 由 dsh_launcher 启动时固定设为 app_paths.get_dsh_home()。
#
# 本模块由栗栗 Python 层直接读写（「方案乙」），绕开 dsh 的写文件审批门禁，
# 由界面/命令触发，可控、可去重、可删。
#
# 文件格式（frontmatter 只保留 dsh 认可的 name + description 两字段，
# 记忆类型用正文首行的 HTML 注释存，dsh 不解析 body、渲染时也不显示）：
#   ---
#   name: <kebab-case slug>
#   description: <一句话，召回判定用>
#   ---
#   <!-- memory-type: user -->
#
#   <正文：事实 + Why + How to apply>
# ============================================================

import hashlib
import re
from pathlib import Path
from typing import Optional

from tamias import app_paths


# 记忆类型（对齐 Claude Code memory 的 type 分类，供界面分组/过滤）
TYPE_USER = "user"            # 用户是谁 / 偏好
TYPE_FEEDBACK = "feedback"    # 用户对工作方式的反馈（以后照此办）
TYPE_PROJECT = "project"      # 项目事实 / 约束 / 进行中的目标
TYPE_REFERENCE = "reference"  # 外部资料指针（URL / 看板 / 工单）

# 类型 → 注入给模型时的分组标签（让 type 真正有语义，不只是死标签）：
# 模型看到「这是反馈、要照做」vs「这是偏好、自然用上」会区别对待。
# 顺序即注入顺序（user 排最前，与 Claude Code 的 type 权重一致）。
TYPE_LABELS = {
    TYPE_USER: "关于主人的信息/偏好",
    TYPE_FEEDBACK: "主人给你的工作方式反馈（要照做）",
    TYPE_PROJECT: "项目相关的事实/约束",
    TYPE_REFERENCE: "外部资料/链接",
}

# 正文里记忆类型的标记行（HTML 注释，markdown 渲染不可见）
_TYPE_MARKER_RE = re.compile(r"^\s*<!--\s*memory-type:\s*([a-z]+)\s*-->\s*$", re.IGNORECASE)


def skills_root(root: Optional[Path] = None) -> Path:
    """dsh 的 skill 扫描根。

    不给 root = 全局记忆目录（用户级，<DSH_HOME>/skills）；
    给了 root = 指定的根（项目级记忆用 <工作目录>/.dsh/skills）。
    """
    if root is not None:
        return Path(root)
    return app_paths.get_dsh_home() / "skills"


def project_skills_root(cwd) -> Path:
    """项目级记忆目录：<工作目录>/.dsh/skills。

    dsh 的 skill 扫描根 rank 里 <cwd>/.dsh/skills 优先级最高（100），
    干活时项目记忆会先于全局记忆被加载——跟 Claude Code「项目优先于全局」一致。
    """
    return Path(cwd) / ".dsh" / "skills"


def _slug(name: str) -> str:
    """把记忆名转成 kebab-case slug（dsh 要求 skill 名是 [a-z0-9][a-z0-9-]*）。"""
    s = name.strip().lower()
    # 非字母数字统一换成短横，再折叠连续短横、去掉首尾短横
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if not s:
        # 全中文/符号名转不出 ASCII，用原名的短哈希做稳定 id，
        # 避免不同中文记忆全部撞成同一个兜底名
        s = "mem-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return s


def _render(slug: str, description: str, body: str, mem_type: str) -> str:
    """把一条记忆渲染成 SKILL.md 全文。"""
    description = (description or "").strip().replace("\n", " ")
    body = (body or "").strip()
    lines = ["---", f"name: {slug}", f"description: {description}", "---", ""]
    lines.append(f"<!-- memory-type: {mem_type} -->")
    lines.append("")
    lines.append(body)
    return "\n".join(lines) + "\n"


def _parse_frontmatter(text: str) -> tuple[str, str]:
    """解析 SKILL.md 的 frontmatter，返回 (name, description)。缺失给空串。"""
    name = desc = ""
    if text.startswith("---"):
        rest = text[3:]
        end = rest.find("\n---")
        if end != -1:
            block = rest[:end]
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("name:"):
                    name = line[len("name:"):].strip()
                elif line.startswith("description:"):
                    desc = line[len("description:"):].strip()
    return name, desc


def _extract_type(text: str) -> str:
    """从正文解析 memory-type，没写就默认 project。"""
    for line in text.splitlines():
        m = _TYPE_MARKER_RE.match(line.strip())
        if m:
            return m.group(1).lower()
    return TYPE_PROJECT


def _strip_meta(text: str) -> str:
    """去掉 frontmatter 和 memory-type 标记行，只留正文（供界面显示/编辑）。"""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    # 去掉正文首行的 memory-type 标记（以及紧随的空行）
    text = text.lstrip("\n")
    for line in text.splitlines(True):
        if _TYPE_MARKER_RE.match(line.strip()):
            text = text[len(line):]
            break
        # 没匹配到标记行就直接停（说明正文里没有）
        break
    return text.strip() + "\n"


def write_memory_at(slug: str, body: str, description: str = "", mem_type: str = TYPE_PROJECT,
                    root: Optional[Path] = None) -> Path:
    """按指定 slug 写/覆盖一条记忆，返回文件路径（编辑保存用，保留原 slug/描述/类型）。
    root 给 None 写全局，给了写项目级。"""
    directory = skills_root(root) / slug
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(_render(slug, description, body, mem_type), encoding="utf-8")
    return path


def write_memory(name: str, body: str, description: str = "", mem_type: str = TYPE_PROJECT,
                 root: Optional[Path] = None) -> Path:
    """写/覆盖一条记忆，返回文件路径。slug 由 name 生成。

    同名（同 slug）已存在则直接覆盖——合并逻辑由调用方决定（传合并后的正文）。
    root 给 None 写全局，给了写项目级。
    """
    slug = _slug(name)
    return write_memory_at(slug, body, description or name, mem_type, root=root)


def list_memories(root: Optional[Path] = None) -> list[tuple[str, str, str, Path]]:
    """列出某根目录下所有记忆，返回 [(slug, description, mem_type, path)]，按 slug 排序。
    root 给 None 列全局，给了列项目级。"""
    r = skills_root(root)
    if not r.is_dir():
        return []
    out = []
    for sk in sorted(r.glob("*/SKILL.md")):
        try:
            text = sk.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _, desc = _parse_frontmatter(text)
        out.append((sk.parent.name, desc, _extract_type(text), sk))
    return sorted(out, key=lambda t: t[0])


def list_all(cwd: Optional[str] = None) -> list[tuple[str, str, str, Path]]:
    """合并全局 + 项目级记忆，返回 [(slug, desc, type, path)]。

    cwd 给 None 只列全局；给了 cwd 就把项目级（<cwd>/.dsh/skills）也并进来。
    项目级排前、同名 slug 项目优先（与 Claude Code「项目优先于全局」一致）。
    """
    out: list[tuple[str, str, str, Path]] = []
    seen: set[str] = set()
    if cwd:
        for item in list_memories(project_skills_root(cwd)):
            if item[0] not in seen:
                out.append(item)
                seen.add(item[0])
    for item in list_memories():
        if item[0] not in seen:
            out.append(item)
            seen.add(item[0])
    return out


def read_memory(slug: str, root: Optional[Path] = None) -> str:
    """读某条记忆的正文（去掉 frontmatter / 类型标记），不存在返回空串。"""
    path = skills_root(root) / slug / "SKILL.md"
    if not path.exists():
        return ""
    try:
        return _strip_meta(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def read_memory_full(slug: str, root: Optional[Path] = None) -> str:
    """读某条记忆的完整 SKILL.md 原文（含 frontmatter），供「编辑原文件」用。"""
    path = skills_root(root) / slug / "SKILL.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def delete_memory(slug: str, root: Optional[Path] = None) -> bool:
    """删某条记忆（整个目录），返回是否真的删掉了。"""
    directory = skills_root(root) / slug
    if not directory.is_dir():
        return False
    try:
        for p in directory.iterdir():
            p.unlink()
        directory.rmdir()
        return True
    except OSError:
        return False


def _body_from_path(path: Path) -> str:
    """从 SKILL.md 路径读正文（去掉 frontmatter / 类型标记），读坏返回空串。"""
    try:
        return _strip_meta(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def _extract_links(body: str) -> list:
    """从正文里提取 [[name]] 交叉引用（记忆之间的关联）。

    栗栗的记忆靠「全文注入」+ [[name]] 互相指路：模型读到正文里的 [[咖啡口味]]
    就知道还有一条「咖啡口味」记忆。这里抽出来，将来记忆页可以做「相关记忆」。
    """
    return re.findall(r"\[\[([^\]]+)\]\]", body or "")


def build_memory_block(cwd: Optional[str] = None) -> str:
    """把记忆拼成一段文本，注入给模型（聊天塞 system prompt、干活塞任务消息）。

    格式 = 索引（每条一行描述，按 type 分组）+ 详情（全文正文）。
    聊天链是纯文本模型、读不了文件，所以正文也一起内联——记忆条数少，直接
    全量注入最可靠；将来记忆多了再改成「只注入索引、正文按需读」（dsh 的
    skill 工具本来就能按名加载正文，那套留给干活链按需走）。

    cwd 给 None 只取全局记忆（聊天没有「项目」概念）；
    给了 cwd 就把项目级记忆（<cwd>/.dsh/skills）也并进来（干活有目录）。
    没记忆返回空串，调用方直接跳过、不加多余前缀。
    """
    memories = list_all(cwd)
    if not memories:
        return ""

    lines = ["【主人长期告诉你的事】（如果和当前对话/任务相关就自然用上，别刻意复述「我记得」）："]

    # 索引：按 type 分组，一条一行描述（对应 Claude Code 的 MEMORY.md 索引）
    for mem_type, label in TYPE_LABELS.items():
        group = [m for m in memories if m[2] == mem_type]
        if not group:
            continue
        lines.append(f"- {label}：")
        for slug, desc, _t, _p in group:
            lines.append(f"  · {desc or slug}")

    # 详情：全文正文内联（聊天链读不了文件，只能内联；条数少，全量注入可靠）
    lines.append("")
    lines.append("【详情】")
    for slug, desc, _t, path in memories:
        body = _body_from_path(path).strip()
        lines.append(f"### {desc or slug}")
        lines.append(body)
        lines.append("")

    return "\n".join(lines).strip()


# ============================================================
# 模块级自测：写 → 列 → 读 → 删 走一遍（用完即清，不留脏数据）
# ============================================================
if __name__ == "__main__":
    print("全局记忆目录 =", skills_root())
    name = "自测记忆-用户喜欢拿铁"
    slug = _slug(name)
    p = write_memory(name, "用户喜欢喝拿铁、去冰。\n\n**Why:** 测试用\n**How to apply:** 点单时按此偏好",
                     "用户偏好：咖啡口味", TYPE_USER)
    print("已写入 =", p)
    print("slug =", slug)
    print("列表 =", list_memories())
    print("正文 =", repr(read_memory(slug)))

    # 项目级：写到一个临时目录，验证 list_all 合并 + build_memory_block
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    write_memory("项目约束-用 Python3.11", "这个项目必须用 Python 3.11，别用 3.12。",
                 "项目约束：Python 版本", TYPE_PROJECT, root=project_skills_root(tmp))
    all_mem = list_all(str(tmp))
    print("合并后记忆数 =", len(all_mem))
    block = build_memory_block(str(tmp))
    print("记忆注入块：\n" + block)
    print("交叉引用 =", _extract_links("见 [[咖啡口味]] 和 [[项目约束-Python3.11]]"))

    print("删除 =", delete_memory(slug))
    print("删除后列表 =", list_memories())
    # 清理临时目录
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
