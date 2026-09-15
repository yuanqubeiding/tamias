# ============================================================
# 栗栗（Tamias）— 对话历史存储
# ============================================================
# 将每次对话保存为 JSON 文件，支持按项目分组、
# 置顶、删除、加载历史对话。
# ============================================================

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from tamias import app_paths
from tamias.i18n import tr


# ---------- 常量 ----------
# 用户数据目录（开发=项目根/data/conversations，打包=%APPDATA%\Tamias\data\conversations）
DATA_DIR = app_paths.get_data_dir() / "conversations"


class Conversation:
    """单条对话记录"""

    def __init__(self, conv_id: str = "", project_dir: str = ""):
        self.id = conv_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        self.project_dir = project_dir
        self.title = ""
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.pinned = False
        self.messages: list[dict] = []
        self.project_data: dict = {}

    @property
    def filepath(self) -> Path:
        return DATA_DIR / f"{self.id}.json"

    @property
    def date_label(self) -> str:
        try:
            dt = datetime.fromisoformat(self.created_at)
            now = datetime.now()
            if dt.date() == now.date():
                return dt.strftime(tr("今天 %H:%M"))
            elif (now - dt).days < 7:
                return dt.strftime(tr("周%w %H:%M"))
            else:
                return dt.strftime("%m/%d %H:%M")
        except Exception:
            return self.created_at[:10]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_dir": self.project_dir,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pinned": self.pinned,
            "project_data": self.project_data,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        conv = cls()
        conv.id = data.get("id", "")
        conv.project_dir = data.get("project_dir", "")
        conv.title = data.get("title", "")
        conv.created_at = data.get("created_at", "")
        conv.updated_at = data.get("updated_at", "")
        conv.pinned = data.get("pinned", False)
        conv.project_data = data.get("project_data", {})
        conv.messages = data.get("messages", [])
        return conv

    def add_message(self, role: str, content: str):
        self.messages.append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat(),
        })
        self.updated_at = datetime.now().isoformat()
        # 用第一条用户消息做标题
        if not self.title and role == "user":
            self.title = content[:30] + ("..." if len(content) > 30 else "")

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def delete(self):
        if self.filepath.exists():
            self.filepath.unlink()

    def load(self) -> bool:
        if not self.filepath.exists():
            return False
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        conv = Conversation.from_dict(data)
        self.__dict__.update(conv.__dict__)
        return True


class ConversationStore:
    """对话管理器：列举、加载、删除"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def list_all(self) -> list[Conversation]:
        """列出所有对话，置顶优先，按更新时间倒序"""
        convs = []
        for f in sorted(DATA_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                convs.append(Conversation.from_dict(data))
            except Exception:
                pass
        # 置顶在前
        convs.sort(key=lambda c: (not c.pinned, c.updated_at), reverse=False)
        return convs

    def list_by_project(self, project_dir: str) -> list[Conversation]:
        """某项目下的对话"""
        return [c for c in self.list_all()
                if c.project_dir == project_dir]

    def get(self, conv_id: str) -> Optional[Conversation]:
        """加载指定对话"""
        conv = Conversation(conv_id=conv_id)
        if conv.load():
            return conv
        return None

    def pin(self, conv_id: str, pinned: bool = True):
        conv = self.get(conv_id)
        if conv:
            conv.pinned = pinned
            conv.save()

    def delete(self, conv_id: str):
        f = DATA_DIR / f"{conv_id}.json"
        if f.exists():
            f.unlink()

    def create(self, project_dir: str = "") -> Conversation:
        return Conversation(project_dir=project_dir)
