"""通义千问 Provider（OpenAI 兼容接口 · DashScope compatible-mode）。

E2 多模型容灾：当 qwen_enabled=true 且 qwen_api_key 非空时，由 FallbackProvider
在主（Zhipu）异常时自动切换到本 provider。业务代码不直接实例化本类，
统一通过各服务模块的 `_make_provider()` 工厂获取。

接口契约与 ZhipuProvider 完全平行，均继承 LLMProvider。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import get_settings
from app.llm.base import LLMProvider

_CHAT_PATH = "/chat/completions"


class QwenProvider(LLMProvider):
    """通过 DashScope compatible-mode v1 API 调用通义千问系列模型。"""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.qwen_model_chat
        self.api_key = settings.qwen_api_key
        self.base_url = settings.qwen_base_url.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _timeout(self) -> httpx.Timeout:
        settings = get_settings()
        return httpx.Timeout(
            settings.model_timeout_seconds,
            connect=10.0,
            read=settings.model_timeout_seconds,
            write=10.0,
            pool=10.0,
        )

    async def generate(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            resp = await client.post(
                f"{self.base_url}{_CHAT_PATH}", headers=self._headers(), json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}{_CHAT_PATH}",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
