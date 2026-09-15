# ============================================================
# 栗栗（Tamias）— 门禁层
# ============================================================
# 栗栗的核心"大脑"。
# 负责：
# 1. 意图分类：判断用户是想"闲聊"还是"干活"
# 2. 路由分发：闲聊 → DeepSeek，干活 → 干活引擎（Harness）
# 3. 操作拦截：干活引擎要执行系统操作时，弹出确认窗口
# ============================================================

# 门禁实例 5315C816Q0

from enum import Enum
from typing import Optional, Callable

from tamias.i18n import tr
from tamias.persona import Persona


class Intent(Enum):
    """
    用户意图类型
    -----------
    CHAT: 闲聊、问答、日常对话 → 走 DeepSeek API
    TASK: 编程、文件操作、系统任务 → 走干活引擎
    """
    CHAT = "chat"
    TASK = "task"


# ---------- 意图分类提示词 ----------

CLASSIFICATION_PROMPT = """你是一个意图分类器。分析用户的消息，判断用户是想"闲聊"还是想让AI"干活"。

分类规则：
- CHAT（闲聊）：日常对话、问候、提问、情感交流、娱乐话题、天气、新闻等不需要操作电脑的话题
- TASK（干活）：需要写代码、创建/修改文件、执行命令、操作电脑系统等具体任务

如果消息模糊、简短、无法确定意图，请优先判 CHAT（闲聊是默认安全选项，宁可少拦截也不要误拦）。

请只回复一个词：CHAT 或 TASK。

用户消息：{message}

分类结果："""


class Gate:
    """
    门禁层
    -----
    栗栗的决策中心。

    工作流程：
    1. 接收用户消息
    2. 分类意图（CHAT 或 TASK）
    3. CHAT → 直接调用 DeepSeek API 聊天
    4. TASK → 调用干活引擎
    5. 干活过程中如果有系统操作 → 通过 confirm_handler 弹窗确认
    """

    def __init__(self,
                 chat_api,                    # DeepSeekAPI 实例
                 work_handler=None,            # 干活回调函数
                 confirm_handler: Optional[Callable] = None,  # 确认弹窗回调
                 persona=None):                # 人设资源包（口吻话术来源）
        """
        Args:
            chat_api: DeepSeekAPI 实例（用于聊天和意图分类）
            work_handler: 干活回调，签名为 work_handler(message, conv_id=None, ...) -> (ok, text)
            confirm_handler: 确认回调，签名为 confirm_handler(operation_desc) -> bool
            persona: Persona 实例，提供口吻话术（None 则用默认栗栗人设）
        """
        self._chat_api = chat_api
        self._work_handler = work_handler
        self._confirm_handler = confirm_handler
        self._persona = persona or Persona()

        # 统计信息
        self._chat_count = 0    # 闲聊次数
        self._task_count = 0    # 干活次数

    # ---------- 公共接口 ----------

    def process(self, message: str, conv_id=None, on_chunk=None, on_status=None, on_step=None, on_todo=None, on_usage=None) -> dict:
        """
        处理用户消息的主入口。

        Args:
            message: 用户输入的文本
            conv_id: 当前对话 id（透传给干活引擎做会话记忆隔离，每个对话一份）
            on_chunk: 流式增量回调，签名 (text) -> None。闲聊/干活边生成边
                      推文字时逐段回传，供 UI 做打字机效果；None 则一次性返回。
            on_status: 状态回调，签名 (text) -> None。闲聊/干活进行中推一句
                       「正在干嘛」供 UI 标题栏显示；None 则不显示状态。
            on_step: 步骤回调，签名 (state, label) -> None。干活时引擎每开
                     一步推 (state, label)，供 UI 罗列过程；闲聊不用。
            on_usage: token 用量回调，签名 (usage) -> None。干活时引擎每生成
                      一条消息推一份 usage 供 UI 累加；闲聊不用。

        Returns:
            dict: {
                "intent": "chat" | "task",
                "reply": str,           # 给用户的回复
                "confirmed": bool,      # 是否需要确认（TASK 模式）
                "operation": str | None # 待确认的操作描述
            }
        """
        # 第1步：意图分类
        intent = self._classify(message)

        if intent == Intent.CHAT:
            # 闲聊路径
            self._chat_count += 1
            if on_chunk:
                # 流式：边生成边回传（打字机），最后拼出完整 reply。
                # 状态：开始前「正在思考」，收到首个文字增量后转「正在输入」。
                parts = []
                if on_status:
                    on_status(tr("正在思考…"))
                first = True
                usage_bucket = []  # 收 chat_stream 流结束回传的真实 token 用量（用于 UI 校准估算值）
                for chunk in self._chat_api.chat_stream(message, usage_out=usage_bucket):
                    parts.append(chunk)
                    if on_status and first:
                        on_status(tr("正在输入…"))
                        first = False
                    on_chunk(chunk)
                reply = "".join(parts)
                # 流结束拿到真实 usage → 转成 {inputTokens, outputTokens} 回传 UI，
                # 让标题栏的「≈N tokens」校准成准确值（结束前估算、结束即校准）。
                if on_usage and usage_bucket:
                    u = usage_bucket[-1]
                    on_usage({
                        "inputTokens": u.get("prompt_tokens", 0),
                        "outputTokens": u.get("completion_tokens", 0),
                    })
            else:
                reply = self._chat_api.chat(message)
            return {
                "intent": "chat",
                "reply": reply,
                "ok": True,  # 闲聊成功
                "confirmed": True,  # 闲聊不需要确认
                "operation": None,
            }

        else:
            # 干活路径
            self._task_count += 1

            # 先让用户确认（干活需要启动干活引擎）
            confirm_msg = tr(self._persona.phrase("gate_task_confirm"), message)

            # 如果有确认回调，弹出确认窗口
            if self._confirm_handler:
                approved = self._confirm_handler(
                    tr(self._persona.phrase("gate_task_title")),
                    confirm_msg
                )
                if not approved:
                    return {
                        "intent": "task",
                        "reply": tr(self._persona.phrase("gate_task_rejected")),
                        "ok": True,  # 用户主动拒绝，不算失败
                        "confirmed": False,
                        "operation": None,
                    }

            # 用户批准，调用干活引擎
            ok = True
            if self._work_handler:
                try:
                    # work_handler 返回 (ok, text)：ok=False 表示干活失败（超时/卡死/报错），
                    # 这里透传成败标志，让 UI 能「失败停住排队」。
                    ok, reply = self._work_handler(message, conv_id=conv_id, on_chunk=on_chunk, on_status=on_status, on_step=on_step, on_todo=on_todo, on_usage=on_usage)
                except Exception as e:
                    ok, reply = False, tr(self._persona.phrase("gate_task_error"), str(e))
            else:
                # 干活引擎尚未接入
                ok, reply = False, tr(self._persona.phrase("gate_task_no_engine"), message)

            return {
                "intent": "task",
                "reply": reply,
                "ok": ok,
                "confirmed": True,
                "operation": None,
            }

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "chat_count": self._chat_count,
            "task_count": self._task_count,
        }

    # ---------- 内部方法 ----------

    def _classify(self, message: str) -> Intent:
        """
        对用户消息进行意图分类。

        策略：
        1. 先用关键词快速判断
        2. 如果关键词判断不确定，再用 DeepSeek API 做分类

        Args:
            message: 用户消息

        Returns:
            Intent.CHAT 或 Intent.TASK
        """
        # 消息若带"上下文拼接"前缀（chat_dialog 拼的"---"分隔），只取最后一段
        # 原始用户消息来分类，避免历史上下文干扰意图判断——例如历史里出现
        # "code" 会让"你是Claudecode吗"这种身份询问被误判成干活。
        if "\n---\n" in message:
            message = message.rsplit("\n---\n", 1)[-1].strip()

        # --- 第一层：关键词快速分类 ---
        task_keywords = [
            # 中文关键词
            "帮我写", "帮我做", "生成", "创建文件", "改代码", "修改文件",
            "写一个", "做一个", "新建", "编写", "重构", "修复bug",
            "部署", "安装包", "打包", "编译", "运行命令",
            "帮我改", "帮我查", "分析代码", "优化代码",
            # 英文关键词
            "write a", "create a", "generate", "fix bug",
            "refactor", "deploy", "build", "compile",
            "write code", "create file",
        ]

        chat_keywords = [
            "你好", "嗨", "早", "晚安", "怎么样", "天气",
            "聊天", "讲笑话", "故事", "你是谁", "谢谢",
            "今天", "心情", "好玩", "有趣", "哈哈",
            "你是", "你叫什么", "你的名字", "名字是",
            # 常见口语 / 语气词 / 短回应（门禁别太敏感，减少误判成干活）
            "等等", "等一下", "等会儿", "稍等", "等等我",
            "好的", "知道了", "收到", "明白", "了解",
            "嗯", "哦", "啊", "嗯嗯",
            "hello", "hi", "hey", "thanks", "how are you", "ok", "okay",
        ]

        msg_lower = message.lower()

        # 检查干活关键词
        for kw in task_keywords:
            if kw.lower() in msg_lower:
                return Intent.TASK

        # 检查闲聊关键词
        for kw in chat_keywords:
            if kw.lower() in msg_lower:
                return Intent.CHAT

        # --- 第二层：用 DeepSeek 做分类 ---
        # 消息比较长或者关键词匹配失败时，用 AI 分类
        try:
            classification_prompt = CLASSIFICATION_PROMPT.format(message=message)
            result = self._chat_api.chat(
                classification_prompt,
                system_prompt="你是一个精确的意图分类器。只回复 CHAT 或 TASK。",
                save_history=False,
                include_history=False,
            )
            result = result.strip().upper()

            if "TASK" in result:
                return Intent.TASK
            else:
                return Intent.CHAT

        except Exception:
            # 分类失败时默认按闲聊处理
            return Intent.CHAT


# ============================================================
# 模块级测试
# ============================================================
if __name__ == "__main__":
    # 模拟一个简单的 chat_api 用于测试
    class _MockChatAPI:
        def chat(self, message, system_prompt=None):
            # 只检查用户消息的最后一行（因为 prompt 中包含示例关键词）
            # 提取"用户消息："后面的内容
            if "用户消息：" in message:
                user_msg = message.split("用户消息：")[-1].split("\n")[0].strip()
            else:
                user_msg = message

            # 如果消息很短且包含任务关键词，判定为 TASK
            task_kw = ["帮我写", "帮我做", "生成", "创建", "改代码", "修改文件",
                       "写一个", "做一个", "新建", "编写", "重构", "修复",
                       "部署", "打包", "编译", "运行命令", "分析代码", "优化代码"]
            for kw in task_kw:
                if kw in user_msg:
                    return "TASK"
            return "CHAT"

    mock_api = _MockChatAPI()
    gate = Gate(chat_api=mock_api)

    # 测试分类
    test_msgs = [
        ("你好呀栗栗！", Intent.CHAT),
        ("今天天气怎么样？", Intent.CHAT),
        ("帮我写一个Python脚本", Intent.TASK),
        ("重构一下这个模块", Intent.TASK),
        ("讲个笑话吧", Intent.CHAT),
        ("帮我创建一个config.yaml文件", Intent.TASK),
    ]

    print("=" * 50)
    print("测试：gate.py 意图分类")
    print("=" * 50)

    all_pass = True
    for msg, expected in test_msgs:
        result = gate._classify(msg)
        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_pass = False
        print(f"[{status}] \"{msg}\" → {result.value} (expected: {expected.value})")

    # 测试 process 方法
    print(f"\n[测试] process 方法：")
    r1 = gate.process("你好")
    print(f"  CHAT: intent={r1['intent']}, confirmed={r1['confirmed']}")

    r2 = gate.process("帮我写代码")
    print(f"  TASK: intent={r2['intent']}, confirmed={r2['confirmed']}")

    stats = gate.get_stats()
    print(f"\n[统计] chat={stats['chat_count']}, task={stats['task_count']}")

    if all_pass:
        print(f"\n[全部测试通过] OK")
    else:
        print(f"\n[有测试失败]")
