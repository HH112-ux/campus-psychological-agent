"""LLM Provider 抽象：模型无关适配层（预留通义千问适配位）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    """统一的大模型调用接口。"""

    #: 上层允许的调用次数上限（含首次尝试）。默认 2 = 原「失败重试 1 次」。
    #: 容灾 provider（如 FallbackProvider）内部已完成主备切换，应把它设为 1，
    #: 否则「上层重试 × 主备切换」会相乘放大真实调用次数与费用。
    max_attempts: int = 2

    @abstractmethod
    async def generate(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> str:
        """非流式生成，返回完整文本。"""

    @abstractmethod
    def stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> AsyncIterator[str]:
        """流式生成，逐段产出增量文本。"""
