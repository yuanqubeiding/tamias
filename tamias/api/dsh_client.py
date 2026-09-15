# ============================================================
# 栗栗（Tamias）— DeepSeek Harness (dsh) 桥接客户端
# ============================================================
# 通过 HTTP + WebSocket 与 dsh web 服务器（默认 127.0.0.1:3080）通信。
#
# 这是「承重墙」的地基：栗栗不再 subprocess 调 Claude Code CLI，
# 而是当「循环主人 + 门禁主人」，dsh 当引擎。
#
# dsh 用的是 Typert 协议，分两半：
# 1. HTTP RPC（一问一答）：
#    POST /api/<method>，请求体是 client-request 信封
#    {type:"client-request", rpcId, method, payload}
#    响应是 server-response 信封
#    {type:"server-response", rpcId, result:{ok, value|error}}
# 2. 事件流（服务端单向推送）：
#    WebSocket 连 /api/events.mux，服务端只下行推送（客户端不能发消息）
#    每帧 JSON：{type:"server-request", rpcId, method, payload}
#    - session/event      会话流式事件（token、工具调用等）
#    - approval/requested 引擎请求审批（栗栗弹窗给用户看）
#    - session/subscribed 订阅确认
#    - stream/error       流错误
#
# 审批闭环：
#    收到 approval/requested 帧 → 用户点允许/拒绝
#    → POST /api/respond 回 client-response 信封（rpcId 原样回填）
#    → 引擎继续跑，最终结果走 session/event 流出来
# ============================================================

import json
import uuid
import threading
import asyncio
import time
from typing import Optional, Callable

import requests
from tamias.i18n import tr
from tamias.app_log import log

# websockets 是异步库（asyncio）；栗栗前端是 PySide6（同步事件循环），
# 所以事件流要放在独立线程里跑自己的 asyncio 循环。
try:
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:  # 打包环境万一漏了这个依赖，降级为「只有 RPC、没有实时流」
    websockets = None
    _HAS_WEBSOCKETS = False


# ---------- 常量 ----------

DEFAULT_BASE_URL = "http://127.0.0.1:3080"
DEFAULT_TIMEOUT = 30  # HTTP RPC 单次超时（秒）
_RECONNECT_DELAY = 3  # WebSocket 断线重连间隔（秒）


# ---------- 工具函数 ----------

def _new_rpc_id() -> str:
    """生成一个 RPC 请求 ID（UUID 字符串）。"""
    return str(uuid.uuid4())


class DshError(Exception):
    """
    dsh RPC 调用失败时抛出的异常。
    携带引擎返回的错误码与详细信息，方便上层提示用户。
    """

    def __init__(self, code: str, message: str, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


# ============================================================
# DshClient — HTTP RPC 门面（同步）
# ============================================================

class DshClient:
    """
    dsh web 服务器的 HTTP RPC 客户端。

    封装会话管理、工作区、审批应答等「一问一答」接口。
    事件流（审批请求、token 流）由 DshEventStream 负责，两者可共享同一个
    base_url，栗栗把它们组合起来用。

    使用方式：
        client = DshClient(base_url="http://127.0.0.1:3080")
        sess = client.session_create(cwd="<工作目录>")
        client.session_prompt(sess["sessionId"], "帮我写个脚本")
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    # ---------- 底层 RPC ----------

    def _rpc(self, method: str, payload: dict) -> dict:
        """
        发一个 HTTP RPC 请求，返回 result.value（已拆信封）。

        Args:
            method: 方法名，如 "session.create"、"session.list"
            payload: 方法参数（dict）

        Returns:
            引擎返回的 value（dict）

        Raises:
            DshError: 引擎返回 ok=false（业务错误）
            requests.RequestException: 网络/HTTP 层错误
        """
        rpc_id = _new_rpc_id()
        envelope = {
            "type": "client-request",
            "rpcId": rpc_id,
            "method": method,
            "payload": payload,
        }
        url = f"{self.base_url}/api/{method}"

        resp = self._session.post(
            url,
            json=envelope,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        # HTTP 层失败（连接被拒、426 upgrade required 等）直接抛，让上层接住
        resp.raise_for_status()

        body = resp.json()
        result = body.get("result", {})
        if not result.get("ok", False):
            err = result.get("error", {})
            raise DshError(
                err.get("code", "unknown"),
                err.get("message", tr("引擎返回未知错误")),
                err.get("details", {}),
            )
        return result.get("value", {})

    # ---------- 会话 ----------

    def session_create(self, cwd: Optional[str] = None,
                       workspace_id: Optional[str] = None,
                       session_id: Optional[str] = None,
                       agent_preset: Optional[str] = None) -> dict:
        """
        创建一个会话（并启动它空闲的 agent）。

        记忆关键：可预分配 session_id。同一个 session_id + cwd 重试会返回
        同一个会话（幂等），这是栗栗「记住之前聊到哪」的地基——把 session_id
        存下来，下次带着它创建/恢复即可。

        Args:
            cwd: 会话工作目录（workspace_id 二选一）
            workspace_id: 工作区 ID（cwd 二选一）
            session_id: 预分配的会话 ID（记忆用）
            agent_preset: 用哪个 agent 预设（如 "code"），不传用默认

        Returns:
            {"sessionId": str, "agentPreset": str|None}
        """
        payload = {}
        if workspace_id is not None:
            payload["workspaceId"] = workspace_id
        elif cwd is not None:
            payload["cwd"] = cwd
        # 空字符串的 session_id 视为「不传」（等同 None）：引擎对空字符串的
        # `payload.sessionId ?? randomUUID()` 不生效，会原样返回空 id 污染记忆。
        if session_id:
            payload["sessionId"] = session_id
        if agent_preset is not None:
            payload["agentPreset"] = agent_preset
        return self._rpc("session.create", payload)

    def session_list(self) -> list:
        """
        列出所有持久化会话（updatedAt 降序）。

        Returns:
            [SessionSummary, ...]，每个含 sessionId/updatedAt/blank/cwd 等
        """
        value = self._rpc("session.list", {})
        return value.get("items", [])

    def session_prompt(self, session_id: str, text: str,
                       mode: str = "queue",
                       client_time_zone: Optional[str] = None) -> dict:
        """
        给某个会话发一条消息，让引擎开始干活。

        Args:
            session_id: 目标会话
            text: 用户消息文本
            mode: "queue"（排队，正常聊天）或 "steer"（纠偏，插话改方向）
            client_time_zone: 浏览器时区，栗栗非浏览器调用可不传

        Returns:
            {"accepted": True, "command": {...}|None}
        """
        payload = {
            "sessionId": session_id,
            "mode": mode,
            "content": [{"type": "text", "text": text}],
        }
        if client_time_zone is not None:
            payload["clientTimeZone"] = client_time_zone
        return self._rpc("session.prompt", payload)

    def session_history(self, session_id: str,
                        before_seq: Optional[int] = None,
                        max_messages: Optional[int] = None) -> dict:
        """
        读一个会话的历史事件（栗栗恢复对话 / 补拉漏掉的输出用）。

        Args:
            session_id: 目标会话
            before_seq: 从某个序号往前翻页（None = 最新一页）
            max_messages: 最多取几条消息

        Returns:
            {"events": [HistoryEntry, ...], "hasMore": bool, "projections": ...}
        """
        payload = {"sessionId": session_id}
        if before_seq is not None:
            payload["beforeSeq"] = before_seq
        if max_messages is not None:
            payload["maxMessages"] = max_messages
        return self._rpc("session.history", payload)

    def session_cancel(self, session_id: str) -> dict:
        """停止某个会话当前正在进行的回合。"""
        return self._rpc("session.cancel", {"sessionId": session_id})

    # ---------- 工作区 ----------

    def workspace_list(self) -> list:
        """列出所有工作区。"""
        value = self._rpc("workspace.list", {})
        return value.get("items", [])

    def workspace_create(self, workspace_id: str, name: str, cwd: str) -> dict:
        """
        创建一个工作区（把某个目录纳管到 dsh，会话可挂到它下面）。

        注意：cwd 必须真实存在，且路径里的中文/特殊字符要当心，
        测试阶段先用纯 ASCII 路径最稳妥。
        """
        return self._rpc("workspace.create", {
            "workspaceId": workspace_id,
            "name": name,
            "cwd": cwd,
        })

    # ---------- 审批应答 ----------

    def respond(self, rpc_id: str, session_id: str,
                approval_id: str, outcome: str) -> dict:
        """
        回答引擎的一个审批请求（允许或拒绝）。

        Args:
            rpc_id: approval/requested 帧里带的 rpcId（必须原样回填）
            session_id: 会话 ID
            approval_id: 审批 ID
            outcome: "allowed-once"（允许这一次）或 "rejected"（拒绝）

        Returns:
            载体会执 receipt：{"accepted": True} 或
            {"accepted": False, "reason": "not-pending"|"bad-response"}
        """
        envelope = {
            "type": "client-response",
            "rpcId": rpc_id,
            "result": {
                "ok": True,
                "value": {
                    "sessionId": session_id,
                    "approvalId": approval_id,
                    "outcome": outcome,
                },
            },
        }
        url = f"{self.base_url}/api/respond"
        resp = self._session.post(
            url,
            json=envelope,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        # /api/respond 直接回 receipt，不是 server-response 信封
        return resp.json()

    def answer_question(self, rpc_id: str, session_id: str,
                        answers: list) -> dict:
        """
        回答引擎的一个反问（question/requested）。

        dsh 的 ask_user_question 工具会让引擎暂停、反问用户一个/多个问题。
        栗栗收到 question/requested 帧后展示问题，用户选择后把答案通过
        /api/respond 回传（跟审批共用同一个 respond 端点，靠 rpcId 区分）。

        Args:
            rpc_id: question/requested 帧里带的 rpcId（必须原样回填）
            session_id: 会话 ID
            answers: 结构化答案列表，每项 {id, selected: [label], custom?}

        Returns:
            receipt dict（{"accepted": true} 或 {"accepted": false, ...}）
        """
        envelope = {
            "type": "client-response",
            "rpcId": rpc_id,
            "result": {
                "ok": True,
                "value": {
                    "sessionId": session_id,
                    "answer": {"answers": answers or []},
                },
            },
        }
        url = f"{self.base_url}/api/respond"
        resp = self._session.post(
            url,
            json=envelope,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        # /api/respond 直接回 receipt，不是 server-response 信封
        return resp.json()

    # ---------- 凭据（API Key 在线设置） ----------

    def credentials_describe(self, refs: list) -> dict:
        """
        查询某个凭据是否已配置（出于安全，不返回明文值）。

        Args:
            refs: 凭据引用名列表，如 ["DEEPSEEK_API_KEY"]

        Returns:
            引擎返回的 value（dict），形如
            {"credentials": {"DEEPSEEK_API_KEY": {"configured": bool, ...}}}
        """
        return self._rpc("credentials.describe", {"refs": refs})

    def credentials_set(self, ref: str, value: str) -> dict:
        """
        写入一个凭据（如 DEEPSEEK_API_KEY），立即生效、无需重启引擎。

        Args:
            ref: 凭据名，如 "DEEPSEEK_API_KEY"
            value: 凭据值（明文 Key）

        Returns:
            引擎返回的 value（dict）
        """
        return self._rpc("credentials.set", {"ref": ref, "value": value})

    def credentials_unset(self, ref: str) -> dict:
        """
        删除一个凭据（如 DEEPSEEK_API_KEY），立即生效。

        Args:
            ref: 凭据名，如 "DEEPSEEK_API_KEY"

        Returns:
            引擎返回的 value（dict）
        """
        return self._rpc("credentials.unset", {"ref": ref})


# ============================================================
# DshEventStream — WebSocket 事件流（后台线程）
# ============================================================

class DshEventStream:
    """
    订阅 dsh 的 /api/events.mux 流，接收审批请求 + 会话事件。

    在独立线程跑 asyncio 循环，收到帧后回调到栗栗主线程注册的处理函数。
    断线自动重连。

    使用方式：
        stream = DshEventStream(
            base_url="http://127.0.0.1:3080",
            on_approval=lambda req: print("要审批", req),
            on_event=lambda sid, evt: print("事件", evt),
        )
        stream.start()
        ...
        stream.stop()
    """

    def __init__(self,
                 base_url: str = DEFAULT_BASE_URL,
                 on_approval: Optional[Callable[[str, dict], None]] = None,
                 on_question: Optional[Callable[[str, dict], None]] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 on_connected: Optional[Callable[[], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None,
                 on_frame: Optional[Callable[[str, dict], None]] = None):
        """
        Args:
            base_url: dsh web 服务器地址
            on_approval: 收到 approval/requested 帧时回调，参数 (rpc_id, payload)。
                         rpc_id 是应答审批时必须回填的 ID，payload 是完整请求：
                         {sessionId, approvalId, toolName, callId?, reason?}
            on_question: 收到 question/requested 帧时回调，参数 (rpc_id, payload)。
                         rpc_id 是应答反问时必须回填的 ID，payload 是完整请求：
                         {sessionId, questions: [{id, question, options?, multiSelect?}]}
            on_event: 收到 session/event 帧时回调 (sessionId, event_dict)
            on_connected: 连接建立成功时回调（可用来补拉历史）
            on_error: 连接出错/断线时回调（参数是错误描述）
            on_frame: 通用回调，收到任意帧时回调 (method, payload_dict)
        """
        self.base_url = base_url.rstrip("/")
        # http(s)://host:port → ws(s)://host:port/api/events.mux
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/events.mux"

        self._on_approval = on_approval
        self._on_question = on_question
        self._on_event = on_event
        self._on_connected = on_connected
        self._on_error = on_error
        self._on_frame = on_frame

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None  # 当前活跃的 WebSocket 连接（stop 时关闭它打断阻塞）

    # ---------- 生命周期 ----------

    def start(self):
        """启动后台事件流线程（幂等：已在跑就不重复开）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="dsh-event-stream", daemon=True)
        self._thread.start()

    def stop(self):
        """停止事件流线程（干净退出，不靠 loop.stop 强杀）。"""
        self._stop_event.set()
        loop = self._loop
        ws = self._ws
        # 关闭当前 ws 连接，让 async for 收帧循环自然退出
        if loop is not None and ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ---------- 内部实现 ----------

    def _run(self):
        """后台线程入口：建 asyncio 循环并跑监听循环。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._listen_loop())
        except RuntimeError:
            pass  # stop() 关闭循环时 run_until_complete 可能抛，属正常退出
        finally:
            self._loop.close()
            self._loop = None

    async def _listen_loop(self):
        """连接 WebSocket，循环读帧，断线后重连。"""
        if not _HAS_WEBSOCKETS:
            self._safe_error(tr("缺少 websockets 库，事件流不可用（HTTP RPC 仍可用）"))
            return

        while not self._stop_event.is_set():
            try:
                # 默认 open_timeout 较短，避免卡死；ping 保活由 websockets 自动处理
                async with websockets.connect(self.ws_url, open_timeout=10) as ws:
                    self._ws = ws
                    # 超时诊断：连上记一笔，之后「断线丢事件」靠这条 + session/subscribed 还原
                    log(f"dsh 事件流已连接（{self.ws_url}）")
                    try:
                        if self._on_connected is not None:
                            self._safe_call(self._on_connected)
                        # 服务端单向推送，客户端不发消息；只读
                        async for raw in ws:
                            if self._stop_event.is_set():
                                break
                            self._dispatch(raw)
                    finally:
                        self._ws = None
                # async for 正常结束 = 服务端主动关了连接（dsh 退出/重启），也算断开
                if not self._stop_event.is_set():
                    log("dsh 事件流断开（服务端关闭连接）", "warning")
            except Exception as e:  # 连接失败 / 断线，稍等重连
                if not self._stop_event.is_set():
                    self._safe_error(str(e))
                    # 超时诊断：断线原因记下来——正在跑的任务收不到「回合结束」多半就是这里丢的
                    log(f"dsh 事件流断开：{e}", "warning")
                if self._stop_event.is_set():
                    break
                # 等重连间隔（每 0.1s 查一次 stop，可及时退出）
                for _ in range(int(_RECONNECT_DELAY * 10)):
                    if self._stop_event.is_set():
                        break
                    await asyncio.sleep(0.1)

    def _dispatch(self, raw: str):
        """解析一帧，按 method 分发到对应回调。"""
        try:
            frame = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return  # 坏帧直接跳过，不崩流

        rpc_id = frame.get("rpcId")
        method = frame.get("method", "")
        payload = frame.get("payload", {}) or {}

        if self._on_frame is not None:
            self._safe_call(self._on_frame, method, payload)

        # 超时诊断：订阅确认 / 流错误帧，记下来还原「断线丢没丢回合结束」。
        # session/subscribed 带 lastSeq（服务器已推进到的序号）；若重连后看到它
        # 但一直没等到 turn/end，就说明结束信号在断线窗口里丢了。
        if method == "session/subscribed":
            log(f"dsh 已订阅会话 {payload.get('sessionId', '?')}（lastSeq={payload.get('lastSeq')}）")
        elif method == "stream/error":
            log(f"dsh 事件流错误帧：{payload}", "warning")

        # 审批请求：栗栗门禁的核心触发点（rpc_id 必须回填才能应答）
        if method == "approval/requested":
            if self._on_approval is not None:
                self._safe_call(self._on_approval, rpc_id, payload)
        elif method == "question/requested":
            # 反问请求：引擎要澄清时停下等用户回答（rpc_id 必须回填才能应答）
            if self._on_question is not None:
                self._safe_call(self._on_question, rpc_id, payload)
        elif method == "session/event":
            if self._on_event is not None:
                sid = payload.get("sessionId")
                evt = payload.get("event", {})
                self._safe_call(self._on_event, sid, evt)

    # ---------- 安全回调 ----------

    def _safe_call(self, fn, *args):
        """回调外面包一层 try，用户回调抛错也不影响事件流。"""
        try:
            fn(*args)
        except Exception:
            pass

    def _safe_error(self, message: str):
        if self._on_error is not None:
            self._safe_call(self._on_error, message)


# ============================================================
# DshGateway — 组合门面（RPC + 事件流 + 审批应答串联）
# ============================================================

class DshGateway:
    """
    把 DshClient（RPC）和 DshEventStream（流）拼成栗栗可用的一个整体。

    栗栗只需：
        gw = DshGateway(base_url=..., on_approval=栗栗的弹窗函数)
        gw.start()
        sid = gw.get_or_create_session(cwd="<工作目录>", session_id=记忆里的ID)
        gw.send(sid, "帮我写个脚本")
        # 引擎要审批时自动回调 on_approval(rpc_id, payload)
        # 栗栗弹窗拿到用户选择后调 gw.answer(rpc_id, payload, "allowed-once")

    on_approval 回调签名是 (rpc_id, payload)：rpc_id 原样传给 answer 即可，
    不用网关内部存状态，多个会话并发也互不干扰。

    另外支持「任务委托」：正在干活的 DshTaskRunner 可以用 set_task_handlers()
    临时接管审批/事件回调，跑完再清空。没有任务在跑时若突然来审批请求，
    默认 fail-closed（直接拒绝），保证引擎不会没人管就乱动系统。
    """

    def __init__(self,
                 base_url: str = DEFAULT_BASE_URL,
                 on_approval: Optional[Callable[[str, dict], None]] = None,
                 on_question: Optional[Callable[[str, dict], None]] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 on_connected: Optional[Callable[[], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self.rpc = DshClient(base_url=base_url)
        # 默认处理器（构造时给的，一般不用，主要给测试）
        self._default_approval = on_approval
        self._default_question = on_question
        self._default_event = on_event
        self._default_on_connected = on_connected  # 默认重连回调（构造时给，一般不用）
        # 任务委托（正在干活时由 DshTaskRunner 设置，优先级高于默认）
        self._task_approval: Optional[Callable[[str, dict], None]] = None
        self._task_question: Optional[Callable[[str, dict], None]] = None
        self._task_event: Optional[Callable[[str, dict], None]] = None
        self._task_on_connected: Optional[Callable[[], None]] = None  # 任务级重连回调（断线自愈用）

        self.stream = DshEventStream(
            base_url=base_url,
            on_approval=self._dispatch_approval,
            on_question=self._dispatch_question,
            on_event=self._dispatch_event,
            on_connected=self._on_stream_connected,
            on_error=on_error,
        )

    # ---------- 事件分发 ----------

    def _dispatch_approval(self, rpc_id: str, payload: dict):
        """审批请求进来：优先交给正在干活的委托，否则默认拒绝（fail-closed）。"""
        handler = self._task_approval or self._default_approval
        if handler is not None:
            handler(rpc_id, payload)
        else:
            # 没人管 → 拒绝，绝不让引擎在无人审批时乱动
            try:
                self.answer(rpc_id, payload, "rejected")
            except Exception:
                pass

    def _dispatch_question(self, rpc_id: str, payload: dict):
        """反问请求进来：优先交给正在干活的委托，否则回传空答案（fail-closed 让引擎别干等）。"""
        handler = self._task_question or self._default_question
        if handler is not None:
            handler(rpc_id, payload)
        else:
            # 没人管 → 回传「每问都没选」的空答案，让引擎自己往下走，别卡死
            questions = payload.get("questions", []) or []
            empty = [{"id": q.get("id", ""), "selected": []} for q in questions]
            try:
                self.answer_question(rpc_id, payload.get("sessionId", ""), empty)
            except Exception:
                pass

    def _dispatch_event(self, session_id: str, event: dict):
        """会话事件进来：优先交给正在干活的委托，否则交给默认处理器。"""
        handler = self._task_event or self._default_event
        if handler is not None:
            handler(session_id, event)

    def _on_stream_connected(self):
        """事件流（重）连上：先调默认回调，再调任务级回调（断线自愈补拉历史）。"""
        if self._default_on_connected is not None:
            try:
                self._default_on_connected()
            except Exception:
                pass
        if self._task_on_connected is not None:
            try:
                self._task_on_connected()
            except Exception:
                pass

    def set_task_handlers(self,
                          approval: Optional[Callable[[str, dict], None]] = None,
                          event: Optional[Callable[[str, dict], None]] = None,
                          question: Optional[Callable[[str, dict], None]] = None,
                          on_connected: Optional[Callable[[], None]] = None):
        """
        设置/清空当前任务的回调（正在干活的 DshTaskRunner 用它接管事件流）。

        Args:
            approval: (rpc_id, payload) -> None，处理审批请求
            event: (session_id, event) -> None，处理会话事件
            question: (rpc_id, payload) -> None，处理反问请求
            on_connected: () -> None，事件流（重）连上时回调（断线自愈补拉历史）
        """
        self._task_approval = approval
        self._task_event = event
        self._task_question = question
        self._task_on_connected = on_connected

    # ---------- 启动/停止 ----------

    def start(self):
        self.stream.start()

    def stop(self):
        self.stream.stop()

    # ---------- 会话 ----------

    def get_or_create_session(self, cwd: str, session_id: Optional[str] = None) -> str:
        """
        拿到（或恢复）一个会话 ID。这是记忆的核心：

        - 有 session_id：带着它调 create（幂等），引擎返回同一个会话 → 记忆恢复
        - 无 session_id：新建，返回新 ID，栗栗把它存下来下次用

        Returns:
            sessionId 字符串
        """
        result = self.rpc.session_create(cwd=cwd, session_id=session_id)
        return result.get("sessionId", "")

    def send(self, session_id: str, text: str) -> dict:
        """给会话发消息，开始干活。"""
        return self.rpc.session_prompt(session_id, text)

    # ---------- 审批应答 ----------

    def answer(self, rpc_id: str, payload: dict, outcome: str) -> dict:
        """
        回答一个审批请求。

        Args:
            rpc_id: on_approval 回调收到的 rpcId（原样回填）
            payload: on_approval 回调收到的完整 payload（含 sessionId/approvalId）
            outcome: "allowed-once"（允许这一次）或 "rejected"（拒绝）

        Returns:
            receipt dict
        """
        return self.rpc.respond(
            rpc_id=rpc_id,
            session_id=payload.get("sessionId", ""),
            approval_id=payload.get("approvalId", ""),
            outcome=outcome,
        )

    def answer_question(self, rpc_id: str, payload: dict, answers: list) -> dict:
        """
        回答一个反问请求。

        Args:
            rpc_id: on_question 回调收到的 rpcId（原样回填）
            payload: on_question 回调收到的完整 payload（含 sessionId/questions）
            answers: 结构化答案列表，每项 {id, selected: [label], custom?}

        Returns:
            receipt dict
        """
        return self.rpc.answer_question(
            rpc_id=rpc_id,
            session_id=payload.get("sessionId", ""),
            answers=answers,
        )


# ============================================================
# 模块级测试
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("测试：dsh_client.py（连本地 dsh web 服务器）")
    print("=" * 50)

    client = DshClient(base_url=DEFAULT_BASE_URL)

    # 测试1：列出会话（不依赖 API Key，纯读持久化）
    print("\n[测试1] session.list：")
    try:
        sessions = client.session_list()
        print(f"  会话数：{len(sessions)}")
        for s in sessions:
            print(f"   - {s.get('sessionId')}  blank={s.get('blank')}  cwd={s.get('cwd')}")
    except Exception as e:
        print(f"  失败：{e}")

    # 测试2：新建会话（预分配 ID 验证幂等/记忆）
    print("\n[测试2] session.create（预分配 ID）：")
    test_id = "yy-bridge-test-001"
    try:
        sess = client.session_create(cwd="./test_workspace", session_id=test_id)
        print(f"  返回 sessionId：{sess.get('sessionId')}")
        print(f"  幂等验证：再来一次")
        sess2 = client.session_create(cwd="./test_workspace", session_id=test_id)
        print(f"  第二次 sessionId：{sess2.get('sessionId')}  →  {'相同 ✓（记忆可用）' if sess2.get('sessionId') == sess.get('sessionId') else '不同 ✗'}")
    except Exception as e:
        print(f"  失败：{e}")

    print("\n[测试完成] 说明：session.prompt / 审批应答需要 DeepSeek API Key 才能真正跑通。")
