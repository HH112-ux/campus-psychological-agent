"""LLM Provider 抽象：模型无关适配层（预留通义千问适配位）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    """统一的大模型调用接口。"""

    @abstractmethod
    async def generate(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> str:
        """非流式生成，返回完整文本。"""

    @abstractmethod
    def stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> AsyncIterator[str]:
        """流式生成，逐段产出增量文本。"""
