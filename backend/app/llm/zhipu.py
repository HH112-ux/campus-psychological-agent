"""智谱开放平台 Provider（OpenAI 兼容 v4 接口）。

P0 目标：跑通一次最简调用。P1 起若引入 LangChain，可将本类迁移/包装为
langchain-community ChatZhipuAI，接口不变，业务代码不感知。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import get_settings
from app.llm.base import LLMProvider

_CHAT_PATH = "/chat/completions"


class ZhipuProvider(LLMProvider):
    """通过智谱 v4 API 调用 GLM 系列模型。"""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.model_chat
        self.api_key = settings.zhipu_api_key
        self.base_url = settings.zhipu_base_url.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _timeout(self) -> httpx.Timeout:
        # 流式下 read 表示“两个数据块之间”的最大间隔，持续有数据就不会整体超时
        settings = get_settings()
        return httpx.Timeout(
            settings.model_timeout_seconds,
            connect=10.0,
            read=settings.model_timeout_seconds,
            write=10.0,
            pool=10.0,
        )

    async def generate(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            resp = await client.post(f"{self.base_url}{_CHAT_PATH}", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            async with client.stream("POST", f"{self.base_url}{_CHAT_PATH}", headers=self._headers(), json=payload) as resp:
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
