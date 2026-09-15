# ============================================================
# 栗栗（Tamias）— DeepSeek Harness 任务层封装
# ============================================================
# 把 dsh 的「异步边干边问」打包成栗栗能用的「同步阻塞 run()」。
#
# 这是承重墙的主体：栗栗（PySide6 同步世界）调 run() 干活，
# 内部接管 dsh 的事件流，把
#   - assistant/message → 攒最终回复文本
#   - turn/end          → 「干完了」信号
#   - approval/requested → 转给外部（主线程）弹窗，拿到结果后 answer
#
# 记忆：run() 会通过 get_session_id/set_session_id 两个回调，
# 把会话 ID 存起来，下次带着它恢复（dsh 幂等，返回同一个会话）。
# ============================================================

import threading
import time
from typing import Optional, Callable

from tamias.app_log import log
from tamias.i18n import tr


# ---------- 常量 ----------

DEFAULT_TASK_TIMEOUT = 600  # 一个任务最长等多久（秒），超时判失败

# 卡死看门狗：引擎连续 STALL_TIMEOUT 秒没有任何事件（连 turn/start、流式 chunk 都算）
# 就判「卡死」提前中止，别让测试员傻等满 600 秒。设 180 秒是因为 dsh 自己的工具超时
# 是 120 秒——任何正常工具都不会静默超过 120 秒，180 秒留足余量、又能在 3 分钟内
# 揪出真卡死。「任务量大但一直在动」不会误杀：事件持续进来，看门狗永远不触发。
STALL_TIMEOUT = 180

# 工具名 → 中文状态文案。
# 干活时引擎每调一个工具，标题栏「栗栗」右边就显示一句「正在干嘛」，
# 让主人知道栗栗是在上网搜资料、还是执行命令，而不是干巴巴一句「请稍等」。
# 键是 dsh 事件的工具名（可能带 "tool:" 前缀，_status_for_tool 会先剥掉）。
TOOL_STATUS_MAP = {
    "web_search": "正在上网搜集资料…",
    "web_fetch": "正在上网浏览网页…",
    "bash": "正在执行命令…",
    "pwsh": "正在执行命令…",
    "read": "正在读取文件…",
    "write": "正在写入文件…",
    "edit": "正在编辑文件…",
    "str_replace_editor": "正在编辑文件…",
    "read_image": "正在查看图片…",
    "glob": "正在搜索文件…",
    "grep": "正在搜索文件…",
    "todo_write": "正在整理任务计划…",
    "skill": "正在调用技能…",
    "create_goal": "正在制定计划…",
    "get_goal": "正在制定计划…",
    "update_goal": "正在制定计划…",
    "subagent": "正在调度小助手…",
}

# dsh 引擎错误码 → 给用户看的中文提示。
# 错误码是 dsh 的稳定机器码（@deepseek-ai/dsh-llm 的 HarnessError.code），
# 靠它把「结束原因：error」这种笼统话翻译成用户能懂的根因——
# 否则缺 Key 时用户只看到一句「任务没有成功完成（结束原因：error）」，
# 根本不知道是没填 API Key。映射不到的码退回引擎原文 message 兜底。
ERROR_CODE_MAP = {
    "MISSING_CREDENTIAL": "干活引擎缺 DeepSeek API Key，请到「设置 → API Key」填好并重启栗栗",
    "INVALID_CREDENTIAL": "DeepSeek API Key 无效，请到「设置 → API Key」重新填正确的 Key",
    "QUOTA": "DeepSeek 账户额度不足或已欠费，请到 DeepSeek 平台充值后再试",
    "CONTEXT_WINDOW_EXCEEDED": "这次任务内容太长，超出了模型能处理的长度，请拆小一点再试",
    "RATE_LIMIT": "DeepSeek 请求太频繁被限流了，稍等一会再试",
    "EMPTY_RESPONSE": "模型没有返回内容，请再试一次",
    "NO_ADAPTER": "没有可用的模型通道，请检查模型配置",
}


class DshTaskRunner:
    """
    dsh 干活执行器（同步阻塞）。

    跑在后台线程（栗栗的 _ReplyWorker 线程），调用方把 message 丢进来，
    阻塞等到 dsh 干完（或超时），返回结果 dict。

    使用方式：
        runner = DshTaskRunner(
            gateway=dsh_gateway,
            on_approval=主线程弹窗回调,          # (rpc_id, payload) -> bool
            get_session_id=读记忆的函数,         # (cwd, conv_id) -> str|None
            set_session_id=写记忆的函数,         # (cwd, conv_id, session_id) -> None
        )
        result = runner.run("帮我写个脚本", cwd="<工作目录>")
        # result = {success, output, session_id, error}
    """

    def __init__(self,
                 gateway,
                 on_approval: Callable[[str, dict], bool],
                 on_question: Optional[Callable[[str, dict], list]] = None,
                 get_session_id: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
                 set_session_id: Optional[Callable[[str, Optional[str], str], None]] = None,
                 timeout: int = DEFAULT_TASK_TIMEOUT):
        """
        Args:
            gateway: DshGateway 实例（RPC + 事件流）
            on_approval: 审批回调，签名 (rpc_id, payload) -> bool。
                         在事件流线程被调用，内部应切到主线程弹窗并阻塞返回。
            on_question: 反问回调，签名 (rpc_id, payload) -> list[答案]。
                         在事件流线程被调用，内部应切到主线程弹窗收集回答；
                         返回结构化答案列表（每项 {id, selected, custom?}）。
            get_session_id: 读记忆回调，签名 (cwd, conv_id) -> session_id|None。
                            因为 dsh 规定同 session_id 换 cwd 会冲突，所以记忆要按目录存；
                            再加对话 id（conv_id）维度，让同一目录下每个对话各有一份会话。
            set_session_id: 写记忆回调，签名 (cwd, conv_id, session_id) -> None。
            timeout: 任务超时（秒）
        """
        self._gateway = gateway
        self._on_approval = on_approval
        self._on_question = on_question
        self._get_session_id = get_session_id
        self._set_session_id = set_session_id
        self._timeout = timeout

        # 一轮任务的运行时状态（run() 期间有效）
        self._done = threading.Event()      # turn/end 到了就 set
        self._last_text = ""                # 最后一条 assistant 文本
        self._end_reason = ""               # turn/end 的结束原因（completed 才算成功）
        self._end_error = ""                # turn/end 的详细错误 message（透传给用户）
        self._end_error_code = ""           # turn/end 的详细错误码（如 MISSING_CREDENTIAL）
        self._cur_session_id: Optional[str] = None  # 本轮会话 ID
        self._lock = threading.Lock()       # 保护上面几个共享字段
        self._busy = False                  # 是否有任务在 run() 里跑（并发互斥：一次只干一个活）
        self._busy_lock = threading.Lock()  # 保护 _busy 的原子「检查 + 置位」
        self._cancel_event = threading.Event()  # 「终止」信号：置位后 _do_run 的等待循环提前退出
        self._on_chunk: Optional[Callable[[str], None]] = None  # 本轮流式增量回调（assistant/chunk → UI）
        self._on_status: Optional[Callable[[str], None]] = None  # 本轮状态回调（工具/推理 → 标题栏状态文字）
        self._on_step: Optional[Callable[[str, str], None]] = None  # 本轮步骤回调 (state, label) → 聊天流「过程列表」
        self._on_todo: Optional[Callable[[list], None]] = None  # 本轮计划清单回调（todo/write 的 todos → UI「计划卡」）
        self._on_usage: Optional[Callable[[dict], None]] = None  # 本轮 token 用量回调（assistant/message 的 usage → UI 累加显示）
        self._thinking_open = False  # 「深度思考」步骤是否已开还没收尾（思考算一步）
        # 超时诊断：记「最近一次引擎事件」的一句话描述，心跳/超时日志据此回答「卡在哪」。
        # 由事件流线程写、_do_run 线程读，简单字符串赋值在 GIL 下原子，无需加锁。
        self._last_event_desc = ""   # 如「调用工具 pwsh」「回合结束（completed）」
        self._last_tool_name = ""    # 最近一次工具名（tool/result 时回填，凑「卡在哪个工具」）
        # 卡死看门狗 + 事件时间线：_last_event_ts 记「最近一次任何本会话事件」的时间戳，
        # _do_run 据此判引擎还动不动；_last_log_ts 记「最近一次写进日志」的时间戳，算「距上条几秒」。
        # 都由事件流线程写（简单 float 赋值在 GIL 下原子），无需加锁。
        self._last_event_ts = 0.0
        self._last_log_ts = 0.0
        self._waiting_user = False  # 正在等主人审批/反问时置 True，看门狗跳过（等用户≠引擎卡死）
        self._max_seq = -1  # 本轮已收到的最大事件 seq（断线自愈据此补拉漏掉的事件）

    # ---------- 主入口 ----------

    def run(self, message: str, cwd: str, conv_id: Optional[str] = None,
            on_chunk: Optional[Callable[[str], None]] = None,
            on_status: Optional[Callable[[str], None]] = None,
            on_step: Optional[Callable[[str, str], None]] = None,
            on_todo: Optional[Callable[[list], None]] = None,
            on_usage: Optional[Callable[[dict], None]] = None) -> dict:
        """同步执行一个任务（对外入口）。

        并发互斥：一次只允许一个任务在跑。已有任务在跑时直接回「正在忙」，
        不并发跑——多个 run() 会互相覆盖 _done/_last_text/事件流委托，前一个
        任务永远收不到完成信号、只能挨到 600 秒超时（测试员真机日志坐实）。
        「终止」靠 cancel() 置 _cancel_event 打断 _do_run。
        """
        with self._busy_lock:
            if self._busy:
                return self._fail(None, tr("栗栗正在忙上一个任务呢，等它干完再喊我～"))
            self._busy = True
            self._cancel_event.clear()
        try:
            return self._do_run(message, cwd, conv_id, on_chunk, on_status, on_step, on_todo, on_usage)
        finally:
            with self._busy_lock:
                self._busy = False
            with self._lock:
                self._cur_session_id = None  # 任务结束清残留，断线自愈据此跳过「没在跑」的回放

    def is_running(self) -> bool:
        """当前是否有任务在 _do_run 里跑（供 work_handler 做「忙」互斥快路径）。"""
        with self._busy_lock:
            return self._busy

    def cancel(self):
        """打断正在 _do_run 的任务：置取消信号，等待循环随即提前退出。

        除置本地信号，还要真正调 dsh 的 session.cancel 停掉引擎回合——只置信号
        会让 run() 提前返回，但 dsh 引擎的回合仍在后台继续跑（反问挂起 / 后台任务
        未完成），下次复用同一 session 会把新消息 splice 进这个半死的回合、引擎卡死
        （卡死排查：主人 Esc 终止后下一轮 180 秒纯心跳）。
        """
        # 先拿 session id（此刻 _do_run 还没收尾清空，sid 有效）；再置信号保证 run 一定返回。
        with self._lock:
            sid = self._cur_session_id
        self._cancel_event.set()
        if sid:
            try:
                # 真正停引擎回合；引擎已崩/断连时取消失败也不影响本地收尾，故吞掉异常。
                self._gateway.session_cancel(sid)
            except Exception:
                pass

    def _do_run(self, message: str, cwd: str, conv_id: Optional[str] = None,
                on_chunk: Optional[Callable[[str], None]] = None,
                on_status: Optional[Callable[[str], None]] = None,
                on_step: Optional[Callable[[str, str], None]] = None,
                on_todo: Optional[Callable[[list], None]] = None,
                on_usage: Optional[Callable[[dict], None]] = None) -> dict:
        """
        同步执行一个任务，阻塞到 dsh 干完、被取消、或超时。

        Args:
            message: 用户消息
            cwd: 工作目录（决定沙箱范围 + 记忆键）
            on_chunk: 流式增量回调，签名 (text) -> None。dsh 边生成边推
                      assistant/chunk（text-delta）时逐段回调，供 UI 做打字机效果。
            on_status: 状态回调，签名 (text) -> None。引擎调工具 / 深度推理 /
                       生成文字时逐段回调一句「正在干嘛」，供 UI 标题栏显示状态。
            on_step: 步骤回调，签名 (state, label) -> None。引擎每开一步
                     （思考 / 工具）推一次 doing，收尾时推 done/fail，
                     供 UI 在聊天流里罗列「过程列表」。
            on_todo: 计划清单回调，签名 (todos) -> None。引擎的 todo_write
                     工具每写一次推一份完整清单（[{content, status}]），
                     供 UI 在聊天流里渲染「📋 计划卡」。
            on_usage: token 用量回调，签名 (usage) -> None。引擎每生成一条
                      assistant/message 带一份 usage（input/output/cache/reasoning
                      tokens），逐份推给 UI 累加显示「本轮已用 X tokens」。

        Returns:
            {"success": bool, "output": str, "session_id": str, "error": str|None}
        """
        # 0. 记录本轮的流式回调 + 状态回调 + 步骤回调 + 计划清单回调 + token 用量回调
        self._on_chunk = on_chunk
        self._on_status = on_status
        self._on_step = on_step
        self._on_todo = on_todo
        self._on_usage = on_usage

        # 1. 重置本轮状态
        self._done.clear()
        self._thinking_open = False
        self._last_event_desc = ""   # 超时诊断：本轮还没收到任何引擎事件
        self._last_tool_name = ""
        # 卡死看门狗基线：把「任务开始」当起点，之后 STALL_TIMEOUT 秒内必须见到引擎事件。
        self._last_event_ts = time.time()
        self._last_log_ts = 0.0
        self._waiting_user = False
        self._max_seq = -1  # 断线自愈：本轮事件 seq 从 -1 重新起算
        with self._lock:
            self._last_text = ""
            self._end_reason = ""
            self._end_error = ""
            self._end_error_code = ""
            self._cur_session_id = None

        # 2. 记忆：拿到/恢复会话 ID（按「工作目录@对话id」记，每个对话一份干活上下文）
        old_id = self._get_session_id(cwd, conv_id) if self._get_session_id else None
        try:
            session_id = self._gateway.get_or_create_session(cwd=cwd, session_id=old_id)
        except Exception as e:
            return self._fail(None, tr("创建/恢复会话失败：{}", e))

        with self._lock:
            self._cur_session_id = session_id
        # 存回记忆（幂等，同一个 ID 存多少次都行）
        if self._set_session_id:
            try:
                self._set_session_id(cwd, conv_id, session_id)
            except Exception:
                pass

        # 3. 接管事件流：审批 + 反问 + 事件都路由到本 runner
        self._gateway.set_task_handlers(
            approval=self._handle_approval,
            event=self._handle_event,
            question=self._handle_question,
            on_connected=self._on_reconnected,
        )

        # 4. 发消息，让引擎开始干活
        try:
            self._gateway.send(session_id, message)
        except Exception as e:
            self._gateway.set_task_handlers(None, None)
            return self._fail(session_id, tr("发送消息失败：{}", e))
        # 超时诊断：记下「消息已发出」，之后 600 秒内靠事件日志 + 心跳还原卡在哪。
        log(f"任务已发给引擎（会话 {session_id[:8]}，超时 {self._timeout} 秒）")

        # 5. 阻塞等「干完了」（turn/end）、被取消、或超时。
        # 用短循环 wait（每 0.5 秒醒一次）而不是一次性 wait(600)：这样「终止」
        # 置的 _cancel_event 能被及时看到、真正打断任务，而不是干等满 600 秒。
        finished = False
        stalled = False  # 卡死看门狗是否触发（跟「超时」「取消」区分开，给用户不同的话）
        start = time.time()
        deadline = start + self._timeout
        last_heartbeat = start  # 超时诊断：每 30 秒打一条心跳，暴露「卡了多久、卡在哪」
        while not finished:
            remaining = deadline - time.time()
            if remaining <= 0:
                break  # 超时
            finished = self._done.wait(timeout=min(0.5, remaining))
            if self._cancel_event.is_set():
                break  # 被「终止」打断
            now = time.time()
            if now - last_heartbeat >= 30:
                log(f"干活进行中…已 {now - start:.0f} 秒，最后事件：{self._last_event_desc or '（尚无事件）'}")
                last_heartbeat = now
            # 卡死看门狗：引擎连续 STALL_TIMEOUT 秒一个事件都没有（连 chunk / turn/start 都没），
            # 且不是在等主人审批/反问 → 真卡死（LLM 调用挂住 / 工具死循环），提前中止。
            # 任务量大但在动的话事件持续进来、_last_event_ts 不断刷新，这里永远不触发。
            if not self._waiting_user and now - self._last_event_ts >= STALL_TIMEOUT:
                log(f"引擎疑似卡死：连续 {now - self._last_event_ts:.0f} 秒没有任何事件，最后事件：{self._last_event_desc or '（全程无事件）'}，提前中止", "warning")
                stalled = True
                break

        # 6. 收尾：清空任务委托，取最终文本 + 结束原因
        self._gateway.set_task_handlers(None, None, None)
        with self._lock:
            output = self._last_text
            end_reason = self._end_reason
            end_error = self._end_error
            end_error_code = self._end_error_code

        if self._cancel_event.is_set():
            log(f"任务被终止（主人点了停止，耗时 {time.time() - start:.0f} 秒）")
            return self._fail(session_id, tr("任务已取消（栗栗停下啦）"))
        if stalled:
            # 看门狗触发：跟「超时」区分——超时是「600 秒没等到结束」，卡死是「引擎 N 秒没动静」。
            # 给用户一句能懂的提示，别跟超时混成一句。
            return self._fail(session_id, tr("干活引擎好像卡住了，好一阵子没动静，栗栗先停下来啦，换个说法再试试？"))
        if not finished:
            # 超时诊断：把「等了多久 + 最后卡在哪个事件」写进日志，直接还原超时根因。
            # 「全程无事件」= 引擎没动静（崩了/WS 断了/会话没起）；「卡在工具 X」= 某条命令/请求挂住。
            log(f"任务超时：等了 {time.time() - start:.0f} 秒没收到引擎结束信号，最后事件：{self._last_event_desc or '（全程无事件）'}", "warning")
            return self._fail(session_id, tr("任务超时（{}秒），栗栗已经等不及啦~", self._timeout))

        # 只有 completed 才算成功；error/aborted/blocked 等都是失败。
        # 用 _friendly_error 把引擎的详细错误（缺 Key / Key 无效 / 额度不足…）
        # 翻译成用户能看懂的话，别只甩一句「结束原因：error」。
        if end_reason != "completed":
            log(f"任务结束（结束原因：{end_reason or '未知'}，耗时 {time.time() - start:.0f} 秒）", "warning")
            return self._fail(session_id, self._friendly_error(end_reason, end_error, end_error_code))
        log(f"任务完成（耗时 {time.time() - start:.0f} 秒）")

        if not output.strip():
            # 干了活但没留下文字（纯工具操作），给个兜底提示
            output = tr("（栗栗完成了一轮操作，但没有生成文字说明）")

        return {
            "success": True,
            "output": output,
            "session_id": session_id,
            "error": None,
        }

    # ---------- 事件流回调（在 dsh 事件流线程执行） ----------

    def _handle_approval(self, rpc_id: str, payload: dict):
        """
        引擎请求审批：转给外部弹窗，拿到 bool 后 answer。

        注意：此时引擎已经停下等审批，所以在这里阻塞弹窗是安全的，
        不会漏掉后续事件（引擎暂停了，没有新事件进来）。
        """
        # 超时诊断：量「审批弹窗等了多久」——审批挂起（主人没点）也是任务超时的一大来源。
        t0 = time.time()
        # 看门狗：等主人点审批不算「引擎卡死」——引擎此刻是故意停下等回答。
        # 置 _waiting_user 让 _do_run 跳过卡死判定；答完清掉并重新起算看门狗。
        self._waiting_user = True
        try:
            approved = self._on_approval(rpc_id, payload)
        except Exception:
            approved = False  # 弹窗出错 → 保守拒绝
        finally:
            self._waiting_user = False
            self._last_event_ts = time.time()
        outcome = "allowed-once" if approved else "rejected"
        try:
            self._gateway.answer(rpc_id, payload, outcome)
        except Exception:
            pass
        self._last_event_desc = f"审批{'通过' if approved else '拒绝'}"
        log(f"审批请求 → {'批准' if approved else '拒绝'}（等待 {time.time() - t0:.1f} 秒）")

    def _handle_question(self, rpc_id: str, payload: dict):
        """
        引擎反问用户：转给外部弹窗收集回答，然后 answer 回传。

        跟审批一样，引擎此刻停下等回答，所以在这里阻塞弹窗是安全的。
        没接反问回调、或弹窗出错时，回传「每问都没选」的空答案兜底，
        绝不让引擎卡在没人回答的死等里。
        """
        questions = payload.get("questions", []) or []
        # 看门狗：等主人回答反问不算「引擎卡死」，置 _waiting_user 跳过卡死判定。
        self._waiting_user = True
        try:
            if self._on_question is None:
                answers = self._empty_answers(payload)
            else:
                try:
                    answers = self._on_question(rpc_id, payload)
                except Exception:
                    answers = self._empty_answers(payload)
        finally:
            self._waiting_user = False
            self._last_event_ts = time.time()
        try:
            self._gateway.answer_question(rpc_id, payload, answers or [])
        except Exception:
            pass
        self._last_event_desc = f"反问（{len(questions)} 问）"
        log(f"引擎反问（{len(questions)} 问）")

    @staticmethod
    def _empty_answers(payload: dict) -> list:
        """把 payload 里的每个问题都标成「没选」，拼成空答案列表。"""
        questions = payload.get("questions", []) or []
        return [{"id": q.get("id", ""), "selected": []} for q in questions]

    def _handle_event(self, session_id: str, event: dict):
        """会话事件：只处理本轮会话的，攒文本 + 判断结束。"""
        with self._lock:
            if self._cur_session_id is None or session_id != self._cur_session_id:
                return  # 别的会话的事件，忽略

        # 卡死看门狗：任何本会话事件（含 turn/start、流式 chunk）都算「引擎还活着」，
        # 记时间戳。_do_run 靠它判「连续 N 秒没动静 = 卡死」。
        self._last_event_ts = time.time()
        # 断线自愈：追踪本轮已收到的最大 seq，重连后据此补拉漏掉的事件（尤其 turn/end）
        seq = event.get("seq")
        if isinstance(seq, int):
            self._max_seq = max(self._max_seq, seq)

        etype = event.get("type", "")

        # 回合开始：引擎开始干这轮活。若之后一直没下文，就能区分「没开始」（引擎没反应）
        # 还是「开始了又卡住」（有 turn/start 但之后静默）。
        if etype == "turn/start":
            self._last_event_desc = "回合开始"
            log(f"引擎回合开始{self._event_meta(event)}")

        # 组装好的助手消息 → 提取文字（后写的覆盖先写的，最后剩最终回复）
        elif etype == "assistant/message":
            text = self._extract_text(event)
            if text:
                with self._lock:
                    self._last_text = text
            self._last_event_desc = "助手回复"  # 超时诊断：引擎已产出回复，但未必发了 turn/end
            # token 用量：dsh 在每条 assistant/message 上带 usage（input/output/
            # cache/reasoning tokens），实时推给 UI 累加显示「本轮已用 X tokens」。
            usage = event.get("data", {}).get("usage")
            if usage and self._on_usage:
                try:
                    self._on_usage(usage)
                except Exception:
                    pass  # 用量回调只是展示，出错不影响干活主流程

        # 流式增量：模型边生成边推的 token 文本，逐段回调给 UI（打字机效果）
        elif etype == "assistant/chunk":
            # chunk 可能是 text-delta（可见文字）或 reasoning-delta（深度思考），
            # 按类型分别处理：文字推给 on_chunk，思考推给 on_status 显示「正在深度思考」。
            # 思考也当成一步（见 _thinking_open）：首个思考增量开一步，见文字/见工具就收尾。
            chunk = event.get("data", {}).get("chunk", {})
            ctype = chunk.get("type", "") if isinstance(chunk, dict) else ""
            if ctype == "text-delta":
                # 有可见文字出来 → 「深度思考」这一步收尾
                if self._thinking_open:
                    self._thinking_open = False
                    if self._on_step:
                        self._on_step("done", "")
                text = chunk.get("text", "") or ""
                if text:
                    if self._on_status:
                        self._on_status(tr("正在输入…"))
                    if self._on_chunk:
                        self._on_chunk(text)
                self._last_event_desc = "正在生成文本"  # 超时诊断：流式输出中
            elif ctype == "reasoning-delta":
                # 首个思考增量 → 开一个「正在深度思考」步骤
                if not self._thinking_open:
                    self._thinking_open = True
                    if self._on_step:
                        self._on_step("doing", tr("正在深度思考…"))
                if self._on_status:
                    self._on_status(tr("正在深度思考…"))
                self._last_event_desc = "正在深度思考"  # 超时诊断：深度推理中

        # 工具调用：引擎要上网/读文件/跑命令。过程列表显示「工具名: 具体操作」
        # （如 read: 某文件、bash: mkdir xxx），主人一眼看懂在动啥；标题栏仍用
        # 中文状态（正在读取文件…），两处各取所需。
        elif etype == "tool/call":
            # 从思考切到具体动作，先把「深度思考」这一步收尾
            if self._thinking_open:
                self._thinking_open = False
                if self._on_step:
                    self._on_step("done", "")
            data = event.get("data", {}) or {}
            name = data.get("name", "")
            # 过程列表：优先「工具名: 参数摘要」，摘不到参数再退回中文状态
            detail = self._summarize_args(data.get("arguments"))
            step_label = f"{name}: {detail}" if (name and detail) else self._status_for_tool(name)
            if self._on_status:
                self._on_status(self._status_for_tool(name))
            if self._on_step:
                self._on_step("doing", step_label)
            # 超时诊断：记下「引擎正在调哪个工具」，心跳/超时日志据此还原卡点
            self._last_tool_name = name
            self._last_event_desc = f"调用工具 {name}" if name else "调用工具"
            log(f"引擎调用工具 {name}{self._event_meta(event)}" if name else f"引擎调用工具{self._event_meta(event)}")

        # 工具结果：一次工具调用结束，按 error 判定这一步成（done）败（fail）。
        # 这是「✅/❌」的准确来源——不用靠「下一条事件=上一步完成」去猜。
        elif etype == "tool/result":
            data = event.get("data", {}) or {}
            err = bool(data.get("error"))
            if self._on_step:
                self._on_step("fail" if err else "done", "")
            # 超时诊断：工具执行结束，记结果（成/败），方便看「哪个工具最慢」
            tname = self._last_tool_name or "工具"
            self._last_event_desc = f"{tname} {'失败' if err else '完成'}"
            log(f"工具 {tname} {'失败' if err else '完成'}{self._event_meta(event)}")

        # 计划清单更新：todo_write 工具每写一次就推一份完整清单（last-write-wins，
        # 无部分更新，整体替换），UI 据此重绘「📋 计划卡」（☐待做 / ⏳进行中 / ✅完成）。
        elif etype == "todo/write":
            data = event.get("data", {}) or {}
            todos = data.get("todos") or []
            if self._on_todo:
                try:
                    self._on_todo(todos)
                except Exception:
                    pass  # 计划卡只是展示，出错不影响干活主流程
            self._last_event_desc = "更新任务计划"
            log(f"引擎更新任务计划（{len(todos)} 项）{self._event_meta(event)}")

        # 回合结束 → 干完了（记下原因，completed 才算成功）。
        # reason 结构是 {kind, error?}，kind 只有 "error"/"completed" 这种笼统值，
        # 真正的根因在 reason.error.{message, code} 里（如缺 Key = MISSING_CREDENTIAL），
        # 必须一起存下来，run() 才能把它透传给用户（否则只能看到「结束原因：error」）。
        elif etype == "turn/end":
            reason = event.get("data", {}).get("reason", {})
            kind = reason.get("kind", "") if isinstance(reason, dict) else ""
            err = reason.get("error", {}) if isinstance(reason, dict) else {}
            err_msg = err.get("message", "") if isinstance(err, dict) else ""
            err_code = err.get("code", "") if isinstance(err, dict) else ""
            with self._lock:
                self._end_reason = kind
                self._end_error = err_msg
                self._end_error_code = err_code
            self._last_event_desc = f"回合结束（{kind or '未知'}）"
            # 超时诊断：结束原因 + 错误码 + 错误信息一起记，别只甩一句「error」——
            # 缺 Key / 额度不足等根因都在这，run.log 自己就能看出「为什么没干成」。
            if err_msg or err_code:
                log(f"引擎回合结束：{kind or '未知'}{self._event_meta(event)}（错误码 {err_code or '无'}：{err_msg or '无'}）")
            else:
                log(f"引擎回合结束：{kind or '未知'}{self._event_meta(event)}")
            self._done.set()

    def _on_reconnected(self):
        """断线重连后补拉历史，喂回断线窗口漏掉的事件（尤其 turn/end）。
        在事件流线程执行，与实时事件同线程（无并发）；HTTP 拉历史阻塞几秒可接受。"""
        with self._lock:
            sid = self._cur_session_id
        if not sid or self._max_seq < 0:
            return  # 没在跑任务 / 还没收到任何事件（首次连接），不用补
        try:
            hist = self._gateway.rpc.session_history(sid)
        except Exception as e:
            log(f"断线自愈：拉历史失败（{e}），本轮若漏 turn/end 仍靠看门狗兜底", "warning")
            return
        entries = hist.get("events", []) or []
        missed = []
        for entry in entries:
            evt = entry.get("event") if isinstance(entry, dict) else None
            if not isinstance(evt, dict):
                continue
            seq = evt.get("seq")
            if isinstance(seq, int) and seq > self._max_seq:
                missed.append(evt)
        if not missed:
            return  # 断线窗口没有新事件，或都已收到
        missed.sort(key=lambda e: e.get("seq", 0))
        log(f"断线自愈：补喂 {len(missed)} 条漏掉的事件（seq 从 {self._max_seq + 1} 起）")
        for evt in missed:
            self._handle_event(sid, evt)

    # ---------- 工具函数 ----------

    def _event_meta(self, event: dict) -> str:
        """组装「seq + 距上条日志几秒」的一段注释，附在事件日志末尾。

        seq 能看出重连漏没漏事件（序号跳了就是丢了）；「距上条几秒」能看出引擎
        在哪一步卡了多久（比如「调用工具 X 距上条 0.3s」→「工具 X 完成 距上条 74s」
        = 这工具跑了 74 秒）。只在低频关键事件上调用（turn/start、tool/call、
        tool/result、turn/end），高频的 assistant/chunk 不调，别把 run.log 刷爆。
        """
        seq = event.get("seq")
        now = time.time()
        gap = ""
        if self._last_log_ts > 0:
            gap = f" 距上条 {now - self._last_log_ts:.1f}s"
        self._last_log_ts = now
        return f"{' seq=' + str(seq) if seq is not None else ''}{gap}"

    @staticmethod
    def _extract_text(event: dict) -> str:
        """从 assistant/message 事件里提取纯文本。"""
        try:
            content = event.get("data", {}).get("message", {}).get("content", [])
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "".join(parts)
        except Exception:
            return ""

    @staticmethod
    def _extract_chunk_text(event: dict) -> str:
        """从 assistant/chunk 事件里提取流式文本增量。
        data 结构是 {turn, step, chunk}，chunk 是 StreamChunk；
        只有 type == "text-delta" 的 chunk 才带可见文字（reasoning/tool 增量忽略）。"""
        try:
            chunk = event.get("data", {}).get("chunk", {})
            if isinstance(chunk, dict) and chunk.get("type") == "text-delta":
                return chunk.get("text", "") or ""
            return ""
        except Exception:
            return ""

    @staticmethod
    def _status_for_tool(name: str) -> str:
        """把工具名翻译成一句中文状态（供标题栏显示）。
        工具名可能带 "tool:" 前缀（如 "tool:web_search"），先剥掉再查表；
        查不到就回退成通用的「正在处理…」。"""
        if not name:
            return tr("正在处理…")
        bare = name.split(":")[-1].strip()  # 兼容 "tool:xxx" / "xxx" 两种写法
        return tr(TOOL_STATUS_MAP.get(bare, "正在处理…"))

    @staticmethod
    def _summarize_args(arguments) -> str:
        """从工具参数里摘一段「像人话」的关键值，给过程列表显示「工具名: 具体操作」。
        摘取顺序跟门禁插件 yy-approval-gate.mjs 的 summarize() 保持一致（command /
        file_path / query / url / skill / prompt / description / name），摘不到就返回空串，
        让调用方退回中文状态兜底。超长截断到 100 字符，别让一行命令把过程列表撑爆。"""
        if not isinstance(arguments, dict):
            return ""
        picks = ["command", "file_path", "query", "url", "skill", "prompt", "description", "name"]
        for key in picks:
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                return text if len(text) <= 100 else text[:100] + "…"
        return ""

    @staticmethod
    def _friendly_error(end_reason: str, end_error: str, end_error_code: str) -> str:
        """把结束原因 + 引擎详细错误翻译成用户能看懂的一句中文。
        优先级：错误码映射（缺 Key / Key 无效 / 额度不足…）→ 引擎原文 message
        → 笼统「结束原因：xxx」。目的只有一个：别让用户对着「结束原因：error」
        猜半天，尤其是缺 Key 这种最常见、也最好自己解决的错。"""
        if end_error_code and end_error_code in ERROR_CODE_MAP:
            return tr(ERROR_CODE_MAP[end_error_code])
        if end_error:
            return tr("任务没做成：{}", end_error)
        return tr("任务没有成功完成（结束原因：{}）", end_reason or tr("未知"))

    def _fail(self, session_id: Optional[str], error: str) -> dict:
        return {
            "success": False,
            "output": "",
            "session_id": session_id,
            "error": error,
        }


# ============================================================
# 模块级测试（不依赖 Qt / 不依赖 Key，只验证状态机）
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("测试：dsh_backend.py 状态机（不真连引擎）")
    print("=" * 50)

    # 假网关：不真发 RPC，只记录调用
    class _FakeRpc:
        """假 RPC：session_history 返回预先塞好的历史（断线自愈回放测试用）。"""
        def __init__(self):
            self.history = {"events": []}
        def session_history(self, session_id):
            return self.history

    class _FakeGateway:
        def __init__(self):
            self.sent = []
            self.answered = []
            self.handlers = {}
            self.rpc = _FakeRpc()
        def get_or_create_session(self, cwd, session_id=None):
            return session_id or "fake-session-001"
        def send(self, sid, text):
            self.sent.append((sid, text))
        def answer(self, rpc_id, payload, outcome):
            self.answered.append((rpc_id, payload.get("approvalId"), outcome))
        def set_task_handlers(self, approval=None, event=None, question=None, on_connected=None):
            self.handlers = {"approval": approval, "event": event, "question": question, "on_connected": on_connected}

    gw = _FakeGateway()
    memory = {}  # {cwd: session_id}
    runner = DshTaskRunner(
        gateway=gw,
        on_approval=lambda rpc_id, payload: True,  # 假弹窗：一律批准
        get_session_id=lambda cwd: memory.get(cwd),
        set_session_id=lambda cwd, sid: memory.__setitem__(cwd, sid),
    )

    # 模拟一轮：在后台线程 run，主线程喂事件
    import threading
    result_holder = {}
    t = threading.Thread(target=lambda: result_holder.update(runner.run("帮我写", "D:/x")))
    t.start()

    # 等 run 发完消息、接管了事件流
    time.sleep(0.1)
    # 模拟引擎发 assistant/message → turn/end
    gw.handlers["event"]("fake-session-001", {
        "type": "assistant/message",
        "data": {"message": {"content": [{"type": "text", "text": "写好啦！"}]}},
    })
    gw.handlers["event"]("fake-session-001", {"type": "turn/end", "data": {"reason": {"kind": "completed"}}})
    t.join(timeout=2)

    print(f"发送记录: {gw.sent}")
    print(f"记忆（按目录）: {memory}")
    print(f"结果: {result_holder}")
    assert result_holder.get("success") is True, "状态机失败"
    assert result_holder.get("output") == "写好啦！", "文本提取失败"
    assert memory.get("D:/x") == "fake-session-001", "记忆写入失败"
    print("\n[状态机测试通过] OK")

    # ---- 断线自愈回放测试 ----
    print("\n测试：断线自愈回放（重连后补喂漏掉的 turn/end）")
    gw2 = _FakeGateway()
    # 塞一段「漏掉 turn/end」的历史：seq=1 assistant/message，seq=2 turn/end
    gw2.rpc.history = {"events": [
        {"event": {"type": "assistant/message", "seq": 1, "data": {"message": {"content": [{"type": "text", "text": "补回的答案"}]}}}},
        {"event": {"type": "turn/end", "seq": 2, "data": {"reason": {"kind": "completed"}}}},
    ]}
    runner2 = DshTaskRunner(
        gateway=gw2,
        on_approval=lambda rpc_id, payload: True,
        get_session_id=lambda cwd: None,
        set_session_id=lambda cwd, sid: None,
    )
    result2 = {}
    t2 = threading.Thread(target=lambda: result2.update(runner2.run("帮我写", "D:/y")))
    t2.start()
    time.sleep(0.1)
    # 模拟：只收到 seq=1（assistant/message），seq=2 的 turn/end 在断线窗口丢了
    gw2.handlers["event"]("fake-session-001", {"type": "assistant/message", "seq": 1, "data": {"message": {"content": [{"type": "text", "text": "补回的答案"}]}}})
    # 模拟断线重连：触发 on_connected → 回放历史，应补喂 seq=2 的 turn/end
    gw2.handlers["on_connected"]()
    t2.join(timeout=2)
    print(f"回放结果: {result2}")
    assert result2.get("success") is True, f"回放未补回 turn/end，结果：{result2}"
    assert result2.get("output") == "补回的答案", f"回放文本不对：{result2}"
    print("[断线自愈回放测试通过] OK")
