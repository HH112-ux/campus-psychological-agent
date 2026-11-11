"""通义千问 Provider（OpenAI 兼容接口 · DashScope compatible-mode）。

E2 多模型容灾：当 qwen_enabled=true 且 qwen_api_key 非空时，由 FallbackProvider
在主（Zhipu）异常时自动切换到本 provider。业务代码不直接实例化本类，
统一通过 `app.llm` 工厂获取。

接口契约与 ZhipuProvider 完全平行，均继承 LLMProvider；传输层同样由
`langchain_client` 的 `ChatOpenAI` 承担。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.langchain_client import build_client, chunk_text, to_lc_messages


class QwenProvider(LLMProvider):
    """通过 DashScope compatible-mode v1 API 调用通义千问系列模型。"""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.qwen_model_chat
        self.api_key = settings.qwen_api_key
        self.base_url = settings.qwen_base_url.rstrip("/")

    def _client(self):
        return build_client(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout_seconds=get_settings().model_timeout_seconds,
        )

    async def generate(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024
    ) -> str:
        client = self._client()
        model = client.bind(temperature=temperature, max_tokens=max_tokens)
        try:
            message = await model.ainvoke(to_lc_messages(messages))
        except Exception as exc:  # noqa: BLE001 —— 保持「任意异常由调用方降级」的契约
            raise RuntimeError(f"模型调用失败：{exc}") from exc
        finally:
            await client.root_async_client.close()
        return chunk_text(message)

    async def stream(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        client = self._client()
        model = client.bind(temperature=temperature, max_tokens=max_tokens)
        try:
            async for chunk in model.astream(to_lc_messages(messages)):
                text = chunk_text(chunk)
                if text:
                    yield text
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"模型流式调用失败：{exc}") from exc
        finally:
            await client.root_async_client.close()
