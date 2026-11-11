"""LangChain 模型客户端适配（P0：只提供构件，不改变任何现有调用路径）。

迁移边界：只有 `ZhipuProvider` / `QwenProvider` 允许使用本模块；危机判定、
合规过滤、记忆与 SSE 均在模型层之外，不经过 LangChain。

本模块负责三件事，且只负责这三件事：
1. `to_lc_messages`：把项目内 `list[dict]` 消息转换为 LangChain 消息对象；
2. `chunk_text`：把流式 chunk 的 `content`（可能是 str 或 content block 列表）
   归一化为纯文本增量；
3. `build_client`：按现有超时语义构造 `ChatOpenAI`，并关闭 SDK 内建重试。

`ChatOpenAICompat` 只做一处请求体修正（`max_tokens` 字段名，见类注释）。
"""
from __future__ import annotations

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

#: 已知角色映射；未知角色按用户输入处理，避免丢失内容。
_ROLE_MAP = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}

#: 空 key 占位符：provider 在请求期构造，构造期抛错会绕过调用层的降级分支，
#: 因此这里与旧实现保持一致——真实鉴权失败由 HTTP 层返回，而不是构造失败。
_EMPTY_KEY_PLACEHOLDER = "EMPTY"


class ChatOpenAICompat(ChatOpenAI):
    """修正 OpenAI 新口径的 token 上限字段名。

    langchain-openai 1.x 会把请求体里的 `max_tokens` 改名为
    `max_completion_tokens`（OpenAI 2024-09 后的新参数名），但智谱 v4 与
    DashScope compatible-mode 只认 `max_tokens`：被忽略会失去回复长度上限，
    被拒绝则整条对话链路不可用。这里在请求体层还原字段名。
    """

    def _get_request_payload(self, input_, *, stop: list[str] | None = None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload.pop("max_completion_tokens")
        return payload


def to_lc_messages(messages: list[dict]) -> list[BaseMessage]:
    """把 OpenAI 风格的消息字典转换为 LangChain 消息对象。"""
    converted: list[BaseMessage] = []
    for message in messages:
        role = str(message.get("role", "")).lower()
        content = message.get("content") or ""
        converted.append(_ROLE_MAP.get(role, HumanMessage)(content=content))
    return converted


def chunk_text(chunk) -> str:
    """把流式 chunk 归一化为文本增量。

    兼容两种形态：`content` 为字符串（纯文本模型），或为 content block 列表
    （多模态/结构化输出）。非 text 类型的 block 一律忽略。
    """
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "".join(parts)


def build_client(
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
) -> ChatOpenAI:
    """构造 OpenAI 兼容客户端，超时与重试语义与手写实现逐项对齐。

    - `timeout`：保持 `read=timeout_seconds`、`connect/write/pool=10s`；
      流式下 read 表示两个数据块之间的最大间隔。
    - `max_retries=0`：重试只保留在上层（`provider.max_attempts`），避免
      「SDK 重试 × 上层重试 × 主备切换」相乘放大调用次数。
    """
    return ChatOpenAICompat(
        model=model,
        api_key=api_key or _EMPTY_KEY_PLACEHOLDER,
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(
            timeout_seconds,
            connect=10.0,
            read=timeout_seconds,
            write=10.0,
            pool=10.0,
        ),
        max_retries=0,
    )
