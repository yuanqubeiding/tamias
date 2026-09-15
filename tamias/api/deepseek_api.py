# ============================================================
# 栗栗（Tamias）— DeepSeek API 客户端
# ============================================================
# 封装 DeepSeek API 的聊天补全调用。
# 支持多轮对话、错误重试、超时处理。
# API 文档：https://api-docs.deepseek.com/
# ============================================================

import requests
import time
from typing import Optional, Generator

from tamias.i18n import tr


# ---------- 常量 ----------

DEFAULT_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 30  # 请求超时（秒）
MAX_RETRIES = 2       # 最大重试次数
RETRY_DELAY = 1.0     # 重试间隔（秒）


class DeepSeekAPI:
    """
    DeepSeek API 客户端
    ------------------
    封装聊天补全请求，支持多轮对话和流式响应。

    使用方式：
        api = DeepSeekAPI(api_key="sk-xxx")
        reply = api.chat("你好！")
        # 或流式：
        for chunk in api.chat_stream("你好！"):
            print(chunk, end="")
    """

    def __init__(self,
                 api_key: str,
                 api_base: str = DEFAULT_API_BASE,
                 model: str = DEFAULT_MODEL,
                 timeout: int = DEFAULT_TIMEOUT):
        """
        Args:
            api_key: DeepSeek API Key
            api_base: API 基础地址
            model: 模型名称
            timeout: 请求超时秒数
        """
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout

        # 对话历史（用于多轮对话）
        self._history: list[dict] = []

        # HTTP 会话（复用连接）
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    # ---------- 公共接口 ----------

    def chat(self, message: str, system_prompt: Optional[str] = None,
             save_history: bool = True, include_history: bool = True) -> str:
        """
        发送聊天消息，返回完整回复。

        Args:
            message: 用户消息文本
            system_prompt: 系统提示词（角色设定）
            save_history: 是否把本轮问答写入对话历史（意图分类等一次性调用传 False）
            include_history: 是否带历史上下文（一次性调用传 False，避免历史干扰）

        Returns:
            AI 回复文本

        Raises:
            DeepSeekAPIError: API 调用失败
        """
        # 构建消息列表
        messages = self._build_messages(message, system_prompt, include_history)

        # 发送请求（带重试）
        response = self._request_with_retry(messages, stream=False)

        # 提取回复文本
        reply = response["choices"][0]["message"]["content"]

        # 更新对话历史（一次性调用不写，避免污染多轮上下文）
        if save_history:
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": reply})

        return reply

    def chat_stream(self, message: str,
                    system_prompt: Optional[str] = None,
                    save_history: bool = True,
                    include_history: bool = True,
                    usage_out: Optional[list] = None) -> Generator[str, None, None]:
        """
        发送聊天消息，以流式方式逐步返回回复。
        每个 chunk 是一小段文本。

        Args:
            message: 用户消息文本
            system_prompt: 系统提示词
            save_history: 是否写入对话历史
            include_history: 是否带历史上下文
            usage_out: 可选列表容器，流结束时把真实 token 用量 dict 塞进去
                       （形如 {"prompt_tokens": N, "completion_tokens": N}），
                       供调用方「结束校准」估算值用；None 则不收集。

        Yields:
            回复文本片段（逐字/逐句）
        """
        messages = self._build_messages(message, system_prompt, include_history)

        # 发送流式请求
        response = self._request_with_retry(messages, stream=True)

        full_reply = ""
        for line in response.iter_lines(decode_unicode=True):
            if not line or line.startswith(":"):
                continue

            if line.startswith("data: "):
                data_str = line[6:]  # 去掉 "data: " 前缀

                if data_str.strip() == "[DONE]":
                    break

                try:
                    import json
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # usage 单独拎出来：include_usage 下最后一个 chunk 的 choices 为空，
                # 不能跟 delta 一起解析（否则 choices[0] 抛 IndexError 把 usage 也吞了）。
                if isinstance(data.get("usage"), dict) and usage_out is not None:
                    usage_out.append(data["usage"])

                try:
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                except (KeyError, IndexError):
                    continue
                if content:
                    full_reply += content
                    yield content

        # 更新对话历史
        if save_history:
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": full_reply})

    def clear_history(self):
        """清空对话历史"""
        self._history.clear()

    def set_system_prompt(self, prompt: str):
        """
        设置系统提示词（覆盖对话历史的开头）。

        Args:
            prompt: 系统提示词
        """
        # 移除旧的系统消息
        self._history = [m for m in self._history if m["role"] != "system"]
        # 插入新的
        self._history.insert(0, {"role": "system", "content": prompt})

    def get_balance(self) -> dict:
        """查询账户余额（DeepSeek 官方余额接口，不在 /v1 下）。

        Returns:
            {"total_balance": float, "currency": str}；失败抛 DeepSeekAPIError。
        """
        host = self.api_base.rstrip("/")
        if host.endswith("/v1"):
            host = host[:-3]
        url = f"{host}/user/balance"
        resp = self._session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            raise DeepSeekAPIError(
                tr("余额查询失败 ({})：{}", resp.status_code, self._parse_error(resp)),
                status_code=resp.status_code,
            )
        data = resp.json()
        infos = data.get("balance_infos") or []
        if infos:
            info = infos[0]
            return {
                "total_balance": float(info.get("total_balance") or 0),
                "currency": info.get("currency") or "CNY",
            }
        return {"total_balance": 0.0, "currency": "CNY"}

    # ---------- 内部方法 ----------

    def _build_messages(self, message: str,
                        system_prompt: Optional[str] = None,
                        include_history: bool = True) -> list[dict]:
        """
        构建 API 请求的 messages 列表。
        包含系统提示词（如果有）+ 历史对话 + 当前消息。
        """
        messages = []

        # 系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 历史对话（一次性调用不带历史，避免干扰）
        if include_history:
            messages.extend(self._history)

        # 当前消息
        messages.append({"role": "user", "content": message})

        return messages

    def _request_with_retry(self, messages: list[dict],
                            stream: bool = False):
        """
        发送 API 请求（带重试逻辑）。

        Args:
            messages: 消息列表
            stream: 是否流式

        Returns:
            API 响应 JSON 或流式 Response 对象

        Raises:
            DeepSeekAPIError: 所有重试均失败
        """
        url = f"{self.api_base}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if stream:
            # 流式也请求 usage（DeepSeek 兼容 OpenAI 的 stream_options）：
            # 让聊天流在结束时返回真实 token 用量，供 UI 把「估算 ≈N」校准成准确值。
            payload["stream_options"] = {"include_usage": True}

        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    stream=stream,
                )

                if response.status_code == 200:
                    if stream:
                        return response
                    return response.json()

                # 非 200 状态码
                error_msg = self._parse_error(response)
                if response.status_code in (401, 403):
                    # 认证错误，不重试
                    raise DeepSeekAPIError(
                        tr("API Key 无效或权限不足：{}", error_msg),
                        status_code=response.status_code
                    )
                if response.status_code == 429:
                    # 限流，等待后重试
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    time.sleep(wait_time)
                    continue

                last_error = DeepSeekAPIError(
                    tr("API 返回错误 ({})：{}", response.status_code, error_msg),
                    status_code=response.status_code
                )

            except requests.exceptions.Timeout:
                last_error = DeepSeekAPIError(
                    tr("请求超时（{}秒），请检查网络连接", self.timeout),
                    status_code=None
                )
            except requests.exceptions.ConnectionError as e:
                last_error = DeepSeekAPIError(
                    tr("网络连接失败：{}", e),
                    status_code=None
                )
            except DeepSeekAPIError:
                raise  # 不重试的错误直接抛出
            except Exception as e:
                last_error = DeepSeekAPIError(
                    tr("未知错误：{}", e),
                    status_code=None
                )

            # 重试前等待
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))

        raise last_error or DeepSeekAPIError(tr("未知错误"))

    def _parse_error(self, response) -> str:
        """解析 API 错误响应"""
        try:
            data = response.json()
            return data.get("error", {}).get("message", response.text)
        except Exception:
            return response.text


class DeepSeekAPIError(Exception):
    """DeepSeek API 调用异常"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
