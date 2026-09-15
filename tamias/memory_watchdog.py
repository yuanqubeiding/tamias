# ============================================================
# 栗栗（Tamias）— 内存看门狗
# ============================================================
# QWebEngine（内嵌 Chromium，显示 Live2D 立绘）跟 Claude Desktop 是同一套
# 架构，跑久了会越占越多内存（同类实测 20GB+）。这里用后台定时器周期量
# 「进程树内存」，一旦超过阈值就触发回收回调（刷新立绘 + 清会话记忆），
# 把泄漏的内存周期性释放，永远涨不到爆。
# 思路 = Chrome 杀标签页重开：根除做不到，控制住 100% 能做到。
# ============================================================

import ctypes
import os
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer

# 阈值（MB）：超过就触发回收。1.5GB = 1536MB。
DEFAULT_THRESHOLD_MB = 1536
# 检查间隔（毫秒）：每 60 秒量一次。
DEFAULT_INTERVAL_MS = 60000
# 回收后冷却（毫秒）：触发一次回收后这段时间内不再量、不再触发，避免
# 「回收没把内存降下来」时每 60 秒 reload 一次立绘、立绘反复闪。
DEFAULT_COOLDOWN_MS = 600000  # 10 分钟


# ---------- Windows 结构体 + API 签名（量进程内存用） ----------

class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


# 固定签名，避免 64 位 HANDLE 被默认 int 截断
_kernel32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi

_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32First.restype = wintypes.BOOL
_kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32)]
_kernel32.Process32Next.restype = wintypes.BOOL
_kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32)]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
_psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wintypes.DWORD]

_PROCESS_QUERY_INFORMATION = 0x0400
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _ws_bytes(pid: int) -> int:
    """单个进程的 WorkingSet（字节），拿不到返回 0。"""
    h = _kernel32.OpenProcess(_PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
    finally:
        _kernel32.CloseHandle(h)
    return 0


def process_tree_working_set_mb() -> float:
    """量「当前进程 + 所有直接子进程（含 QtWebEngineProcess.exe）」的
    WorkingSet 总和（MB）。泄漏主要在 Chromium 子进程，只量主进程会漏掉它。"""
    total = _ws_bytes(os.getpid())

    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        return total / (1024 * 1024)
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        if _kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                if entry.th32ParentProcessID == os.getpid():
                    total += _ws_bytes(entry.th32ProcessID)
                if not _kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        _kernel32.CloseHandle(snapshot)

    return total / (1024 * 1024)


class MemoryWatchdog(QObject):
    """内存看门狗：周期量进程树内存，超阈值触发回收回调。"""

    def __init__(self, threshold_mb=DEFAULT_THRESHOLD_MB,
                 interval_ms=DEFAULT_INTERVAL_MS, parent=None,
                 cooldown_ms=DEFAULT_COOLDOWN_MS):
        super().__init__(parent)
        self._threshold_mb = threshold_mb
        self._interval_ms = interval_ms
        self._cooldown_s = cooldown_ms / 1000.0
        self._cooldown_until = 0.0  # 冷却结束时间戳（time.monotonic 秒），冷却期内跳过检查
        self._reclaim_cb = None
        self._reclaiming = False  # 回收动作重入保护
        self._last_mb = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)

    def set_reclaim_callback(self, cb):
        """设置回收回调：cb(mb)，在内存超阈值时调用。"""
        self._reclaim_cb = cb

    def start(self):
        """开始周期检查。"""
        self._timer.start(self._interval_ms)

    def _check(self):
        """量一次内存；超阈值则触发回收（回收期间 / 冷却期内不重入）。"""
        if self._reclaiming:
            return
        if time.monotonic() < self._cooldown_until:
            return  # 回收后冷却期内：跳过，防止「没降下来」时每 60 秒 reload 一次立绘
        try:
            mb = process_tree_working_set_mb()
        except Exception:
            return  # 量内存失败（如非 Windows）就跳过，不打扰主流程
        self._last_mb = mb
        if mb >= self._threshold_mb:
            self._reclaiming = True
            try:
                if self._reclaim_cb:
                    self._reclaim_cb(mb)
            finally:
                self._reclaiming = False
            # 触发回收后进入冷却期，避免回收无效时反复 reload（配合回调里的延迟验证）
            self._cooldown_until = time.monotonic() + self._cooldown_s

    @property
    def last_mb(self) -> float:
        """最近一次量到的内存（MB）。"""
        return self._last_mb
