"""智谱开放平台 Provider（OpenAI 兼容 v4 接口）。

传输层由 `langchain_client` 的 `ChatOpenAI` 承担；本类只保留项目内契约：
构造参数、`max_attempts`、`generate` / `stream` 签名。业务代码与测试替身
均按类名打桩，不感知传输实现。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.langchain_client import build_client, chunk_text, to_lc_messages


class ZhipuProvider(LLMProvider):
    """通过智谱 v4 API 调用 GLM 系列模型。"""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.model_chat
        self.api_key = settings.zhipu_api_key
        self.base_url = settings.zhipu_base_url.rstrip("/")

    def _client(self):
        """每次调用新建客户端，用完即关：与旧实现「每调用一个 httpx 客户端」一致。"""
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
