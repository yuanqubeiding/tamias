# ============================================================
# 栗栗（Tamias）— 工作区（workspace）动作编排
# ============================================================
# 存放「工作区 / 项目」相关的动作编排——凡是不纯属于聊天 UI 的
# 逻辑（打开项目、拖拽入口解析、切项目、清会话等）优先放这里，
# 而不是塞进 chat_dialog.py（它已超载，见记忆 file-placement-guideline）。
#
# 现状说明（2026-09-05）：核心项目状态（_current_project / _working_dir）
# 仍住在 chat_dialog 里，等以后重构再迁过来。本文件先承接「拖拽入口」
# 这类纯逻辑，把骨架立起来。
# ============================================================

import os


def resolve_project_folder(paths):
    """从拖入的本地路径列表解析出「要打开的项目文件夹」路径。

    规则：
    - 取第一个路径（多个时忽略其余，避免一次误开一堆项目）；
    - 是文件夹 → 直接用；
    - 是文件 → 取其所在文件夹（拖文件 = 打开它所在的项目）；
    - 空列表 / 无效路径 → 返回 None（调用方忽略本次拖拽）。
    """
    if not paths:
        return None
    p = (paths[0] or "").strip()
    if not p:
        return None
    if os.path.isdir(p):
        return p
    # 文件 → 所在文件夹（os.path.dirname 对盘符根如 "C:\\" 也返回自身）
    return os.path.dirname(p)


def is_drive_root(path):
    """判断一个路径是不是盘符根（"C:\\"/"C:/"/"D:" 等）。
    盘符根不能当项目/工作目录：dsh 建会话时会 mkdir(cwd) 确保目录存在，而盘符根
    本来就不能被「创建」→ EPERM（"failed to ensure project directory"）。判据：
    普通目录的 dirname 会去掉最后一级，盘符根的 dirname 等于它自己。"""
    try:
        p = os.path.abspath(path or "")
        return bool(p) and os.path.dirname(p) == p
    except Exception:
        return False
