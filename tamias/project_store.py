# ============================================================
# 栗栗（Tamias）— 项目存储
# ============================================================
# 项目 > 对话。所有对话都挂在某个项目下（含内置「日常闲聊」）。
# ============================================================

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from tamias import app_paths
from tamias.i18n import tr


# 用户数据目录（开发=项目根/data，打包=%APPDATA%\Tamias\data）
DATA_DIR = app_paths.get_data_dir()
PROJECTS_DIR = DATA_DIR / "projects"

# 「日常闲聊」内置项目：所有对话都挂在某个项目下，闲聊默认落这个项目。
# folder 必须是字符串（要写进 registry 的 JSON，Path 无法序列化）。
CHITCHAT_PROJECT_ID = "__chitchat__"
CHITCHAT_NAME = "日常闲聊"
CHITCHAT_FOLDER = str(DATA_DIR / "日常闲聊")


class Conversation:
    """单条对话"""

    def __init__(self, conv_id: str = "", title: str = ""):
        self.id = conv_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        self.title = title
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.pinned = False
        self.messages: list[dict] = []
        self.project_data: dict = {}

    @property
    def date_label(self) -> str:
        try:
            dt = datetime.fromisoformat(self.created_at)
            now = datetime.now()
            if dt.date() == now.date():
                return dt.strftime(tr("今天 %H:%M"))
            elif (now - dt).days < 7:
                return f"{dt.strftime('%a')} {dt.strftime('%H:%M')}"
            return dt.strftime("%m/%d %H:%M")
        except Exception:
            return self.created_at[:10]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "pinned": self.pinned, "messages": self.messages,
            "project_data": self.project_data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        c = cls()
        c.id = data.get("id", ""); c.title = data.get("title", "")
        c.created_at = data.get("created_at", ""); c.updated_at = data.get("updated_at", "")
        c.pinned = data.get("pinned", False)
        c.messages = data.get("messages", [])
        c.project_data = data.get("project_data", {})
        return c

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content, "time": datetime.now().isoformat()})
        self.updated_at = datetime.now().isoformat()
        if not self.title and role == "user":
            self.title = content[:30] + ("..." if len(content) > 30 else "")


def _load_conversation_file(path: Path) -> Optional[Conversation]:
    """读单个对话 JSON；文件不存在或写坏都返回 None，不抛异常（防 dsh 写坏导致栗栗崩溃）"""
    try:
        if path.exists():
            return Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        pass
    return None


class Project:
    """一个项目 = 一个文件夹 + 多对话 + 共享面板"""

    def __init__(self, proj_id: str = "", name: str = "", folder: str = ""):
        self.id = proj_id or uuid.uuid4().hex[:10]
        self.name = name
        self.folder = folder
        self.plan = ""; self.progress = ""; self.issues = ""
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    @property
    def _data_dir(self) -> Path:
        """项目文件夹内的 .tamias/ 目录"""
        return Path(self.folder) / ".tamias" if self.folder else PROJECTS_DIR / self.id

    @property
    def dir(self) -> Path:
        return self._data_dir

    @property
    def work_dir(self) -> str:
        """记忆隔离用的工作目录：有 folder 用 folder，否则退回 data/projects/<id>"""
        return self.folder or str(self._data_dir)

    @property
    def convs_dir(self) -> Path:
        return self._data_dir / "conversations"

    @property
    def meta_file(self) -> Path:
        return self._data_dir / "project.json"

    def to_dict(self) -> dict:
        # 对话列表单独存文件，不在这个 dict 里
        return {
            "id": self.id, "name": self.name, "folder": self.folder,
            "plan": self.plan, "progress": self.progress, "issues": self.issues,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        p = cls()
        p.id = data.get("id", ""); p.name = data.get("name", "")
        p.folder = data.get("folder", ""); p.plan = data.get("plan", "")
        p.progress = data.get("progress", ""); p.issues = data.get("issues", "")
        p.created_at = data.get("created_at", ""); p.updated_at = data.get("updated_at", "")
        return p

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.convs_dir.mkdir(parents=True, exist_ok=True)
        self.meta_file.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self):
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def list_conversations(self) -> list[Conversation]:
        convs = []
        if not self.convs_dir.exists():
            return convs
        for f in sorted(self.convs_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                convs.append(Conversation.from_dict(json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                pass
        # 排序：置顶的排前面，组内按「最近更新」新→旧。
        # 分两趟稳定排序：先按时间倒序，再按是否置顶（稳定，保持时间序不被破坏）。
        convs.sort(key=lambda c: c.updated_at, reverse=True)
        convs.sort(key=lambda c: not c.pinned)
        return convs

    def save_conversation(self, conv: Conversation):
        self.convs_dir.mkdir(parents=True, exist_ok=True)
        (self.convs_dir / f"{conv.id}.json").write_text(
            json.dumps(conv.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def delete_conversation(self, conv_id: str):
        f = self.convs_dir / f"{conv_id}.json"
        if f.exists():
            f.unlink()


class ProjectStore:
    """项目与对话的统一管理"""

    def __init__(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def _registry_file(self) -> Path:
        return PROJECTS_DIR / "_registry.json"

    def _read_registry(self) -> dict:
        if self._registry_file.exists():
            try: return json.loads(self._registry_file.read_text(encoding="utf-8"))
            except Exception: pass
        return {}

    def _write_registry(self, data: dict):
        self._registry_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 项目 ----------

    def ensure_chitchat_project(self) -> Project:
        """幂等建/取「日常闲聊」内置项目（重启不重复建）"""
        existing = self.get_project(CHITCHAT_PROJECT_ID)
        if existing:
            return existing
        p = Project(proj_id=CHITCHAT_PROJECT_ID, name=CHITCHAT_NAME, folder=CHITCHAT_FOLDER)
        p.save()
        reg = self._read_registry()
        reg[p.id] = {"name": CHITCHAT_NAME, "folder": CHITCHAT_FOLDER}
        self._write_registry(reg)
        return p

    def get_chitchat_project(self) -> Project:
        """取「日常闲聊」项目；不存在则自动建"""
        return self.ensure_chitchat_project()

    def create_project(self, name: str, folder: str) -> Project:
        p = Project(name=name, folder=folder)
        p.save()
        # 注册
        reg = self._read_registry(); reg[p.id] = {"name": name, "folder": folder}
        self._write_registry(reg)
        return p

    def list_projects(self) -> list[Project]:
        projects = []
        reg = self._read_registry()
        for pid, info in reg.items():
            p = Project(proj_id=pid, name=info.get("name",""), folder=info.get("folder",""))
            if p.meta_file.exists():
                try:
                    p = Project.from_dict(json.loads(p.meta_file.read_text(encoding="utf-8")))
                    projects.append(p)
                except Exception: pass
        return sorted(projects, key=lambda p: p.updated_at, reverse=True)

    def get_project(self, proj_id: str) -> Optional[Project]:
        reg = self._read_registry()
        info = reg.get(proj_id, {})
        p = Project(proj_id=proj_id, name=info.get("name",""), folder=info.get("folder",""))
        if p.meta_file.exists():
            try:
                return Project.from_dict(json.loads(p.meta_file.read_text(encoding="utf-8")))
            except Exception:
                # project.json 被写坏（常见：dsh 干活时顺手改了又没写对 JSON）。
                # 不崩：重建一个空项目（保留 id/name/folder，清空面板），
                # 下次 save 会写回合法 JSON，栗栗不至于因为一个坏文件直接退出。
                p.plan = p.progress = p.issues = ""
                try:
                    p.save()
                except Exception:
                    pass
                return p
        return None

    def get_project_by_folder(self, folder: str) -> Optional[Project]:
        """按文件夹路径反查项目（打开文件夹时去重：同一个文件夹不重复建项目）。

        学 VSCode「Open Folder」：文件夹即项目。先在注册表里按归一化路径找，
        找不到就兜底读 <folder>/.tamias/project.json（比如项目从别的机器拷过来、
        或 data/ 目录被清掉只剩项目文件夹时，照样能认回原项目，不新建覆盖）。
        匹配前统一归一化（绝对路径 + 大小写/斜杠），避免 D:\\foo 和 d:\\foo\\ 当成两个。
        """
        target = os.path.normcase(os.path.abspath(folder))
        reg = self._read_registry()
        for pid, info in reg.items():
            f = info.get("folder", "")
            if f and os.path.normcase(os.path.abspath(f)) == target:
                return self.get_project(pid)
        # 兜底：注册表没有，但文件夹里已有 .tamias/project.json → 直接读 meta 还原
        meta = Path(folder) / ".tamias" / "project.json"
        if meta.exists():
            try:
                p = Project.from_dict(json.loads(meta.read_text(encoding="utf-8")))
                # 顺手补回注册表，下次就能直接反查到，不用再走兜底
                reg[p.id] = {"name": p.name, "folder": p.folder}
                self._write_registry(reg)
                return p
            except Exception:
                pass
        return None

    def delete_project(self, proj_id: str) -> bool:
        """删除项目；内置「日常闲聊」不可删，返回是否删成功"""
        if proj_id == CHITCHAT_PROJECT_ID:
            return False
        reg = self._read_registry()
        info = reg.pop(proj_id, {})
        self._write_registry(reg)
        if info.get("folder"):
            p = Project(proj_id=proj_id, folder=info["folder"])
            p.delete()
        return True

    def save_project(self, proj: Project):
        proj.updated_at = datetime.now().isoformat()
        proj.save()
        reg = self._read_registry(); reg[proj.id] = {"name": proj.name, "folder": proj.folder}
        self._write_registry(reg)
