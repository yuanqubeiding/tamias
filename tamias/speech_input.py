# -*- coding: utf-8 -*-
"""语音输入封装：按住说话 → Windows 离线识别 → 文字。

依赖（MIT，可选）：winrt-Windows.Media.SpeechRecognition / Globalization /
Foundation / Foundation.Collections（PyWinRT 3.x，随 requirements.txt 声明）。
没装这些包时本模块整体降级，不崩主程序。

架构：SpeechRecognizer 得在它自己创建的线程里跑 WinRT 事件，故用一个
后台 daemon 线程常驻 asyncio 事件循环；主线程（Qt）通过
run_coroutine_threadsafe 把 start/stop 提交过去，识别结果经 Qt Signal
（跨线程自动 queued 到主线程）发回。
"""
import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from tamias.i18n import tr

try:
    from winrt.windows.media.speechrecognition import (
        SpeechRecognizer, SpeechRecognitionResultStatus,
    )
    _WINRT_OK = True
except Exception:  # 没装 winrt 包 → 语音输入不可用，整体降级
    _WINRT_OK = False

# Windows「语音识别」隐私权限没开时的 OSError 错误码（HRESULT 0x80045509）
_SPEECH_PRIVACY_ERR = -2147199735

# 语音识别「无效操作」错误码（HRESULT 0x80131509 = E_INVALIDOPERATION）。
# 识别会话已在运行 / 麦克风被占用或没插好时，start_async 会抛这个。
_SPEECH_INVALIDOP_ERR = -2146233079


class SpeechInput(QObject):
    """按住说话转文字。对外的三个信号 + start()/stop()。"""

    text_ready = Signal(str)   # 松手后识别出的文字（"" = 没识别到）
    error = Signal(str)        # 出错提示（系统语音权限没开 / 没装语言包等）
    available = Signal(bool)   # 语音识别是否可用（后台初始化成功后发一次）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._latest = ""             # 最近一次识别成功的话
        self._loop = None             # 后台 asyncio 事件循环
        self._ok = False              # 识别器是否初始化成功
        self._ready = threading.Event()
        self._thread = None
        self._running = False         # 识别会话是否正在运行（防重复 start 触发 E_INVALIDOPERATION）
        if _WINRT_OK:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    # ---------- 后台线程 ----------
    def _worker(self):
        """后台线程：建事件循环 + 识别器，常驻等 start/stop。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            # 默认用系统语音语言（中文系统 → 中文识别）
            self._sr = SpeechRecognizer()
            self._sess = self._sr.continuous_recognition_session
            self._sess.add_result_generated(self._on_result)
            self._ok = True
        except Exception as e:  # 没装语音语言包等 → 不可用
            self._err_msg = tr("语音识别不可用：{}", str(e))
        self._ready.set()
        self.available.emit(self._ok)
        if not self._ok:
            self.error.emit(self._err_msg)
        self._loop.run_forever()

    def _on_result(self, sender, args):
        """WinRT 事件回调（后台线程）。只收「识别成功」的一段话，覆盖式保留最后一句。"""
        r = args.result
        if r.text and r.status == SpeechRecognitionResultStatus.SUCCESS:
            self._latest = r.text

    # ---------- 主线程调用的对外接口 ----------
    def wait_ready(self, timeout=3.0):
        """阻塞等后台线程初始化完，返回是否可用（供初始化/测试用）。"""
        if self._thread:
            self._ready.wait(timeout)
        return self._ok

    def is_available(self) -> bool:
        return self._ok

    def start(self):
        """按住：开始识别。"""
        if not self._ok or not self._loop:
            return
        if self._running:
            return  # 已在识别中：忽略重复 start（按住 Alt + 点语音按钮会触发两次）
        self._running = True
        self._latest = ""
        asyncio.run_coroutine_threadsafe(self._start(), self._loop)

    def stop(self):
        """松手：停止识别，把最后识别出的话经 text_ready 发回。"""
        if not self._ok or not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._stop(), self._loop)

    async def _start(self):
        try:
            await self._sess.start_async()
        except OSError as e:
            self._running = False  # 启动失败：复位运行标志，允许下次重试
            if getattr(e, "winerror", None) == _SPEECH_PRIVACY_ERR:
                self.error.emit(tr("语音识别权限没开：请到 Windows 设置 → 隐私和安全性 → 语音，打开「语音识别」后再按住说话。"))
            elif getattr(e, "winerror", None) == _SPEECH_INVALIDOP_ERR:
                self.error.emit(tr("语音识别启动失败：可能是麦克风被占用或没插好，请检查后重试。"))
            else:
                self.error.emit(tr("语音识别启动失败：{}", str(e)))
        except Exception as e:
            self._running = False  # 启动失败：复位运行标志，允许下次重试
            self.error.emit(tr("语音识别启动失败：{}", str(e)))

    async def _stop(self):
        try:
            await self._sess.stop_async()
        except Exception:
            pass
        self._running = False  # 无论 stop 成败都复位，允许下次 start
        self.text_ready.emit(self._latest)
