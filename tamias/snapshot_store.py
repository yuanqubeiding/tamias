# ============================================================
# 栗栗（Tamias）— 干活回滚快照存储
# ============================================================
# 回滚的「数据层」：读写 <工作目录>/.tamias/snapshots/ 下的快照和清单。
# 快照由门禁插件 yy-approval-gate.mjs（Node 侧）在改文件落盘前写好，
# 本模块负责：列清单、撤销（单文件 / 一键全部）、清空、给对比视图喂内容。
#
# 目录结构（参照 Claude Code file-history）：
#   <工作目录>/.tamias/snapshots/
#     <sha256(绝对路径)前16位>     ← 改前原文（新建文件则为空文件）
#     manifest.json                ← { 指纹: {path, saved_at, existed_before} }
#
# 撤销语义：
#   existed_before=true  → 快照文件存的是改前原文，撤销 = 写回
#   existed_before=false → 改前不存在（新建），撤销 = 删除文件
# 撤销即消费：还原成功后删掉该快照 + 从 manifest 移除（「只留一版」的轻量定位）。
# ============================================================

import json
import shutil
from pathlib import Path


class SnapshotStore:
    """干活回滚快照：列清单 / 撤销 / 清空 / 喂对比内容。"""

    def __init__(self, work_dir: str):
        # 快照根目录：<工作目录>/.tamias/snapshots/
        self.snap_root = Path(work_dir) / ".tamias" / "snapshots"

    # ---------- manifest 读写 ----------

    def _manifest_file(self) -> Path:
        return self.snap_root / "manifest.json"

    def _read_manifest(self) -> dict:
        """读 manifest.json；不存在或损坏返回空 dict。"""
        try:
            if self._manifest_file().exists():
                return json.loads(self._manifest_file().read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _write_manifest(self, manifest: dict) -> None:
        """写回 manifest.json（ensure_ascii=False 保留中文路径）。"""
        try:
            self._manifest_file().parent.mkdir(parents=True, exist_ok=True)
            self._manifest_file().write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ---------- 清单 ----------

    def list_snapshots(self) -> list:
        """列出当前所有快照，返回 [{hash, path, saved_at, existed_before}]，按时间升序。"""
        manifest = self._read_manifest()
        result = []
        for fp, info in manifest.items():
            result.append({
                "hash": fp,
                "path": info.get("path", ""),
                "saved_at": info.get("saved_at", ""),
                "existed_before": bool(info.get("existed_before", True)),
            })
        result.sort(key=lambda x: x.get("saved_at", ""))
        return result

    def has_snapshots(self) -> bool:
        """是否有可撤销的快照。"""
        return bool(self._read_manifest())

    # ---------- 撤销 ----------

    def restore(self, fp: str) -> bool:
        """按指纹撤销单个文件：把快照覆盖回文件（新建的则删除）。成功返回 True。"""
        manifest = self._read_manifest()
        info = manifest.get(fp)
        if not info:
            return False  # 没这个文件的快照
        path = info.get("path", "")
        snap_file = self.snap_root / fp
        try:
            if info.get("existed_before", True):
                # 改前存在 → 把快照原文写回
                if not snap_file.exists():
                    return False
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(snap_file.read_bytes())
            else:
                # 改前不存在（新建）→ 撤销 = 删除
                Path(path).unlink(missing_ok=True)
        except Exception:
            return False
        # 撤销成功 → 消费掉快照（删文件 + 从 manifest 移除）
        try:
            snap_file.unlink(missing_ok=True)
            del manifest[fp]
            self._write_manifest(manifest)
        except Exception:
            pass  # 清理失败不影响撤销结果本身
        return True

    def restore_all(self) -> tuple:
        """一键全部撤销：把当前所有快照都还原。返回 (成功数, 失败数)。"""
        ok = fail = 0
        for fp in list(self._read_manifest().keys()):
            if self.restore(fp):
                ok += 1
            else:
                fail += 1
        return ok, fail

    # ---------- 对比视图内容 ----------

    def read_before(self, fp: str) -> str:
        """读「改之前」快照内容（文本，二进制兜底成 replace）。"""
        snap_file = self.snap_root / fp
        try:
            return snap_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def read_after(self, path: str) -> str:
        """读「改之后」当前内容（文本）；文件已删/不存在返回空串。"""
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""
        except Exception:
            return ""

    # ---------- 清理 ----------

    def clear(self) -> None:
        """清空快照目录（新一次干活前调用，实现「只留最近一次任务」）。"""
        shutil.rmtree(self.snap_root, ignore_errors=True)
