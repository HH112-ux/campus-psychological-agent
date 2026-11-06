"""轻量失败率监控（跨实例共享；存储走 `core/counter` 的 memory/redis 双后端）。

原实现是各服务模块内的 `_fail_count` / `_total_count` 进程内全局变量：
多实例部署下每个实例各算各的比率，既可能重复告警、也可能永远凑不齐分母。
改为经 `core/counter` 计数后，Redis 后端下多实例看到同一比率。
不可达时 fail-open：计数为 0、不告警，但不影响主链路。
"""
from __future__ import annotations

import logging

from app.core import counter

logger = logging.getLogger(__name__)


class FailRateCounter:
    """失败率监控：累计达到 min_samples 且失败率超阈值时告警并清零。

    与既有口径一致：≥20 个样本且失败率 >5% 时打印 warning，随后清零重新观察。
    """

    def __init__(
        self,
        name: str,
        *,
        min_samples: int = 20,
        threshold: float = 0.05,
        window_seconds: int = 3600,
    ) -> None:
        self._name = name
        self._min_samples = min_samples
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._total_key = f"metric:{name}:total"
        self._fail_key = f"metric:{name}:fail"

    async def success(self) -> None:
        await counter.incr(self._total_key, self._window_seconds)

    async def failure(self) -> None:
        await counter.incr(self._total_key, self._window_seconds)
        failed = await counter.incr(self._fail_key, self._window_seconds)
        total = await counter.get(self._total_key)
        # Redis 不可达时 total=0（fail-open），此处防御性短路，避免除零
        if total < self._min_samples:
            return
        ratio = failed / total
        if ratio > self._threshold:
            logger.warning(
                "%s 失败率 %.0f%%（%d/%d），触发告警阈值（>%.0f%%）",
                self._name,
                ratio * 100,
                failed,
                total,
                self._threshold * 100,
            )
            await counter.delete(self._total_key, self._fail_key)
