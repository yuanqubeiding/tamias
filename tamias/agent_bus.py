# ============================================================
# 栗栗（Tamias）— Agent 任务总线
# ============================================================
# 多实例协作：通过共享文件夹中的 JSON 文件传递任务。
# 不需要服务端、不需要网络，纯文件系统通信。
# ============================================================

import json
import os
import uuid
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


class AgentBus:
    """栗栗实例间通信总线"""

    def __init__(self, instance_name: str = "栗栗"):
        self._name = instance_name
        self._bus_dir = Path(tempfile.gettempdir()) / "tamias_bus"
        self._bus_dir.mkdir(parents=True, exist_ok=True)
        self._my_id = str(uuid.uuid4())[:8]
        self._last_processed: set[str] = set()  # 已处理的任务文件名
        # 注册自己
        self._register()
        # 启动时就存在的历史任务（上个会话遗留）标记为已处理，避免重启弹旧审批
        self._skip_stale_on_start()

    def _skip_stale_on_start(self):
        """把启动前就存在的 review/result 文件标记为已处理。

        这些是上个会话遗留的多实例协作消息，重启后不应再弹审批。
        """
        for pattern in ("review_*.json", "result_*.json"):
            for f in self._bus_dir.glob(pattern):
                self._last_processed.add(f.name)

    def _register(self):
        """在总线上注册当前实例"""
        registry = self._read_json("_registry.json")
        registry[self._my_id] = {
            "name": self._name,
            "pid": os.getpid(),
            "last_seen": datetime.now().isoformat(),
        }
        self._write_json("_registry.json", registry)

    def unregister(self):
        """注销"""
        registry = self._read_json("_registry.json")
        registry.pop(self._my_id, None)
        self._write_json("_registry.json", registry)

    # ---------- 发送 ----------

    def send_review(self, task: str, plan: str = "",
                    progress: str = "", issues: str = "",
                    code: str = "") -> bool:
        """
        发送审查任务给其他实例。

        Returns: 是否发送成功
        """
        task_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        filename = f"review_{task_id}.json"
        data = {
            "id": task_id,
            "type": "review",
            "from": self._name,
            "from_id": self._my_id,
            "created_at": datetime.now().isoformat(),
            "status": "pending",
            "task": task,
            "plan": plan,
            "progress": progress,
            "issues": issues,
            "code": code,
        }
        self._write_json(filename, data)
        return True

    def send_result(self, review_id: str, result: str,
                    approved: bool = True) -> bool:
        """回传审查结果"""
        filename = f"result_{review_id}.json"
        self._write_json(filename, {
            "review_id": review_id,
            "type": "result",
            "from": self._name,
            "from_id": self._my_id,
            "created_at": datetime.now().isoformat(),
            "approved": approved,
            "result": result,
        })
        return True

    # ---------- 接收 ----------

    def poll(self) -> Optional[dict]:
        """
        轮询新任务（3秒调用一次即可）。

        Returns: 新任务 dict 或 None（没有新任务时）
        """
        for f in sorted(self._bus_dir.glob("review_*.json")):
            if f.name in self._last_processed:
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                # 不处理自己发的任务
                if data.get("from_id") == self._my_id:
                    self._last_processed.add(f.name)
                    continue
                if data.get("status") != "pending":
                    self._last_processed.add(f.name)
                    continue
                self._last_processed.add(f.name)
                return data
            except Exception:
                self._last_processed.add(f.name)
        return None

    def poll_result(self, review_id: str) -> Optional[dict]:
        """轮询审查结果"""
        f = self._bus_dir / f"result_{review_id}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    # ---------- 清理 ----------

    def clean_old(self, max_age_hours: int = 24):
        """清理超过指定时间的旧任务文件"""
        import time
        cutoff = time.time() - max_age_hours * 3600
        for f in self._bus_dir.glob("*.json"):
            if f.name == "_registry.json":
                continue
            if f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                except Exception:
                    pass

    # ---------- 工具 ----------

    def _read_json(self, filename: str) -> dict:
        f = self._bus_dir / filename
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _write_json(self, filename: str, data: dict):
        (self._bus_dir / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8")
