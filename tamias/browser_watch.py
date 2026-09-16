# ============================================================
# 栗栗（Tamias）— 浏览器弹出追踪（诊断用，定位后可删）
# ============================================================
# 目的：锁定「启动栗栗时，dsh 网页（127.0.0.1:3080）被谁弹出来」这个 bug 的真凶。
#
# 现象：启动栗栗会「唤醒网页的 deepseek harness」（浏览器弹出 dsh 网页）。
# 排查发现栗栗和 dsh 两边源码里都没有主动打开浏览器的代码，所以需要一套
# 运行时监控，在复现时抓「浏览器进程到底是被谁 spawn 的」。
#
# 原理：后台 daemon 线程，用系统自带 PowerShell（Get-CimInstance Win32_Process）
#       定期枚举进程，发现「新出现的进程」就记下它的名字 + PID + 父进程 PID +
#       父进程名 + 命令行；浏览器进程、命令行含 3080/localhost 的进程重点标记。
#       复现后读 browser_watch.log，看浏览器进程的父进程 PID 是谁：
#         - 父进程是 dsh 的 node.exe   → dsh 弹的
#         - 父进程是 tamias.exe        → 栗栗弹的
#         - 父进程是 explorer.exe 等   → 系统/用户手动弹的（ShellExecute 委托）
#
# 窗口：启动后监控约 5 分钟自动停（覆盖 dsh 冷启动 180 秒超时 + 就绪后的余量），
#       不长期占资源。线程是 daemon，随进程退出自动结束。
#
# 已知局限：只抓「新进程创建」。若浏览器一直常驻、只是旧标签页自动重连
#          （不产生新进程），日志会是空的——这本身也是有用信息（反证不是
#          栗栗/dsh 主动 spawn 浏览器）。命令行可能读不到（权限受限）时，
#          父进程关系仍会记录，不影响锁定真凶。
# ============================================================

import json
import os
import subprocess
import threading
import time
from datetime import datetime

from tamias.app_log import get_logs_dir, mask_path


# 常见浏览器进程名（含国产壳），命中即重点标记。
_BROWSER_NAMES = {
    "msedge.exe", "chrome.exe", "firefox.exe", "iexplore.exe",
    "360se.exe", "360chrome.exe", "qqbrowser.exe", "sogouexplorer.exe",
    "opera.exe", "brave.exe", "vivaldi.exe", "maxthon.exe",
}

# 命令行命中关键字：进程命令行带这些，很可能就是「打开 dsh 网页」的那一下。
_URL_KEYWORDS = ("3080", "127.0.0.1", "localhost")

_WATCH_SECONDS = 300       # 监控窗口时长（秒）
_POLL_INTERVAL = 1.5       # 轮询间隔（秒）

_watch_started = False


def _log_path():
    """追踪日志文件路径：logs/browser_watch.log（随「导出异常日志」一起带走）。"""
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "browser_watch.log"


def _ps_script() -> str:
    """PowerShell 脚本：强制 UTF-8 输出 + 枚举所有进程的 PID/父PID/名字/命令行。"""
    return (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId, ParentProcessId, Name, CommandLine | "
        "ConvertTo-Json -Compress"
    )


def _snapshot_processes() -> dict:
    """调 PowerShell 拿当前所有进程：{pid: (name, ppid, cmdline)}。失败返回空。"""
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _ps_script()],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if cp.returncode != 0:
            return {}
        raw = cp.stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return {}
        items = json.loads(raw)
        # ConvertTo-Json：单个对象返回 dict、多个返回 list，统一成 list
        if isinstance(items, dict):
            items = [items]
        snap = {}
        for it in items:
            try:
                pid = int(it.get("ProcessId"))
                snap[pid] = (
                    str(it.get("Name") or ""),
                    int(it.get("ParentProcessId") or 0),
                    str(it.get("CommandLine") or ""),
                )
            except Exception:
                continue
        return snap
    except Exception:
        return {}


def _watch_loop():
    """后台监控循环：轮询进程快照，发现新进程就落盘一条。"""
    log_file = _log_path()

    def _write(line):
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    _write(f"===== 浏览器弹出追踪开始 {datetime.now().isoformat()}，监控 {_WATCH_SECONDS} 秒 =====")

    # 基准快照：追踪启动瞬间已存在的进程不算「新」，只盯之后冒出来的。
    known_pids = set(_snapshot_processes().keys())
    deadline = time.time() + _WATCH_SECONDS

    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            snap = _snapshot_processes()
        except Exception:
            continue
        new_pids = set(snap.keys()) - known_pids
        if not new_pids:
            continue
        known_pids |= new_pids  # 先并入已知，避免下一轮重复记录
        for pid in new_pids:
            name, ppid, cmdline = snap.get(pid, ("", 0, ""))
            pname, _, _ = snap.get(ppid, ("?", 0, ""))
            flags = []
            if name.lower() in _BROWSER_NAMES:
                flags.append("浏览器")
            if any(k in cmdline for k in _URL_KEYWORDS):
                flags.append("含3080/localhost")
            mark = (" [" + "+".join(flags) + "]") if flags else ""
            # 命令行脱敏：可能含 C:\Users\<用户名> 等绝对路径，套 mask_path 护住隐私；
            # URL 和进程名不属路径，不受影响，仍能看清 3080 等关键信息。
            _write(
                f"{datetime.now().isoformat()} pid={pid} name={name} "
                f"ppid={ppid} pname={pname}{mark} cmd={mask_path(cmdline)[:400]}"
            )

    _write(f"===== 浏览器弹出追踪结束 {datetime.now().isoformat()} =====")


def start_browser_watch():
    """启动浏览器弹出追踪（幂等：只起一次）。栗栗启动早期调用。"""
    global _watch_started
    if _watch_started:
        return
    _watch_started = True
    threading.Thread(target=_watch_loop, daemon=True).start()
