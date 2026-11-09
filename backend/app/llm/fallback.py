"""E2 多模型容灾：FallbackProvider 封装主/备 provider，主异常自动切备。

设计原则：
- 业务代码只感知 LLMProvider 接口，不关心容灾细节；
- 容灾策略集中在本模块一处定义（日志措辞、异常传播）；
- 备用也失败时抛出原始主 provider 异常（由调用方走既有的降级话术，chat.py
  的 `_generate_nonstream` / `_collect_stream` 本来就有重试 + 降级兜底逻辑）；
- 失败不打全局告警（主链路已有 `alerting.notify_llm_degraded`，本层只记 info，
  避免每句对话切备就轰炸一次值班群）；
- 流式语义：仅当主 provider 未产出任何 chunk 就抛异常时切备；若主已产出部分
  再失败，保留已收文本并让异常自然传播——强行切备会把两段独立 LLM 回复硬拼，
  语义上是错的（与 chat.py 既有的「已收部分则保留」逻辑对齐）。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """主 provider 异常时自动切到备用 provider。

    用法：FallbackProvider(primary=ZhipuProvider(), backup=QwenProvider())
    四个调用点不直接构造本类，而是通过 `app.llm.get_chat_provider()` /
    `get_light_provider()` 工厂根据 `qwen_enabled` 配置决定返回裸主 provider
    还是 FallbackProvider。
    """

    def __init__(self, primary: LLMProvider, backup: LLMProvider) -> None:
        self._primary = primary
        self._backup = backup

    # 本层已在内部做「主 → 备」切换，调用方不应再叠加重试：
    # 上层已有 2 次重试，若这里仍为 2，最坏情况会打 2×2=4 次真实模型调用。
    max_attempts = 1

    async def generate(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024
    ) -> str:
        try:
            return await self._primary.generate(messages, temperature, max_tokens)
        except Exception as primary_exc:  # noqa: BLE001
            logger.info(
                "primary provider.generate 异常（%s），切备用",
                type(primary_exc).__name__,
            )
            try:
                return await self._backup.generate(messages, temperature, max_tokens)
            except Exception as backup_exc:  # noqa: BLE001 —— 备用也失败
                # 主异常仍是调用方看到的那个（保持既有降级分支不变），
                # 但把备用异常挂到 __cause__ 上，别让排障时丢掉「备用为什么也没成」。
                logger.info(
                    "backup provider.generate 也异常（%s）",
                    type(backup_exc).__name__,
                )
                raise primary_exc from backup_exc

    async def stream(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """仅当主未产出任何 chunk 就抛异常时切备；已产出部分则重抛让调用方保留。"""
        produced = False
        try:
            async for delta in self._primary.stream(messages, temperature, max_tokens):
                produced = True
                yield delta
        except Exception as primary_exc:  # noqa: BLE001
            if produced:
                # 已有部分产出：重抛给 chat.py 走「保留部分」路径，不拼接两段 LLM 回复
                raise
            # 主完全未产出：切备用例
            logger.info(
                "primary provider.stream 未产出即异常（%s），切备用例",
                type(primary_exc).__name__,
            )
            try:
                async for delta in self._backup.stream(messages, temperature, max_tokens):
                    yield delta
            except Exception as backup_exc:  # noqa: BLE001 —— 备用也失败
                logger.info(
                    "backup provider.stream 也异常（%s）",
                    type(backup_exc).__name__,
                )
                raise primary_exc from backup_exc
