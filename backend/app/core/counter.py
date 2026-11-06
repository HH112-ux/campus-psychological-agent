"""跨实例共享的轻量状态：告警冷却与计数（与限流同源的 memory/redis 双后端）。

背景（M5 生产化）：告警冷却表与失败率计数原为各模块的进程内全局变量，
多实例部署下各算各的——同一高危事件可能被重复推送，或阈值告警永远凑不齐
分母。这与已修复的 G4（内存限流）属同类隐患，故统一收敛到本模块。

后端开关复用 `shared_state_backend`（旧名 `ratelimit_backend`，兼容读取）：
memory（dev/单机）/ redis（生产多实例）。
Redis 不可达时一律 fail-open（冷却视为未冷却 → 允许发送；计数返回 0），
绝不因监控基础设施故障阻断对话主链路。
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import get_settings
from app.core import redis_client

logger = logging.getLogger(__name__)

# INCR + 首次 EXPIRE 原子执行：两步若分开做，进程在间隙崩溃会留下无 TTL 的永久计数键
_INCR_WITH_TTL_LUA = """
local v = redis.call('INCR', KEYS[1])
if v == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return v
"""


async def _redis_safe[T](
    op: Callable[[Any], Awaitable[T]], *, fallback: T, warn: str
) -> T:
    """执行 Redis 操作；不可达时记 warning 并返回 fallback（fail-open 的唯一出口）。"""
    try:
        return await op(await redis_client.get_client())
    except Exception:
        logger.warning(warn, exc_info=True)
        return fallback


class MemoryCounter:
    """进程内实现（dev / 单机 / 测试）。"""

    def __init__(self) -> None:
        self._cooldown: dict[str, float] = {}
        self._counters: dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        self._cooldown.clear()
        self._counters.clear()

    async def cooldown_allows(self, key: str, window_seconds: int) -> bool:
        now = time.monotonic()
        last = self._cooldown.get(key)
        if last is not None and now - last < window_seconds:
            return False
        self._cooldown[key] = now
        return True

    async def clear(self, key: str) -> None:
        self._cooldown.pop(key, None)

    async def incr(self, key: str, window_seconds: int) -> int:
        self._counters[key] += 1
        return self._counters[key]

    async def get(self, key: str) -> int:
        return self._counters.get(key, 0)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._counters.pop(key, None)


class RedisCounter:
    """Redis 实现：冷却 SET NX EX（原子占位）；计数 INCR+EXPIRE Lua 原子化（跨实例共享）。

    所有命令统一经 `_redis_safe` 出口：fail-open 策略（日志措辞、降级返回值）
    只在这一处定义，避免五个方法各自漂移。
    """

    async def cooldown_allows(self, key: str, window_seconds: int) -> bool:
        ok = await _redis_safe(
            lambda c: c.set(key, "1", nx=True, ex=max(1, window_seconds)),
            fallback=True,
            warn="Redis 不可达，冷却判定放行（fail-open）",
        )
        return bool(ok)

    async def clear(self, key: str) -> None:
        await _redis_safe(
            lambda c: c.delete(key),
            fallback=None,
            warn="Redis 不可达，冷却清除失败（忽略）",
        )

    async def incr(self, key: str, window_seconds: int) -> int:
        value = await _redis_safe(
            lambda c: c.eval(_INCR_WITH_TTL_LUA, 1, key, max(1, window_seconds)),
            fallback=0,
            warn="Redis 不可达，计数降级为 0（fail-open）",
        )
        return int(value or 0)

    async def get(self, key: str) -> int:
        value = await _redis_safe(
            lambda c: c.get(key),
            fallback=0,
            warn="Redis 不可达，读取计数降级为 0（fail-open）",
        )
        return int(value or 0)

    async def delete(self, *keys: str) -> None:
        await _redis_safe(
            lambda c: c.delete(*keys),
            fallback=None,
            warn="Redis 不可达，计数清理失败（忽略）",
        )


_memory = MemoryCounter()
_backend: MemoryCounter | RedisCounter | None = None


def _get_backend() -> MemoryCounter | RedisCounter:
    global _backend
    if _backend is None:
        _backend = (
            RedisCounter()
            if get_settings().shared_state_backend.lower() == "redis"
            else _memory
        )
    return _backend


def reset_all() -> None:
    """清空进程内计数与后端缓存（仅供测试使用；不断开 Redis 连接）。"""
    global _backend
    _memory.reset()
    _backend = None


async def cooldown_allows(key: str, window_seconds: int) -> bool:
    """冷却判定：True=允许（首次 / 已过冷却期），False=冷却中。"""
    return await _get_backend().cooldown_allows(key, window_seconds)


async def clear(key: str) -> None:
    """清除冷却标记（用于「发送失败不占冷却、下轮可重试」）。"""
    await _get_backend().clear(key)


async def incr(key: str, window_seconds: int) -> int:
    """自增计数（首次设置窗口 TTL），返回自增后的值。"""
    return await _get_backend().incr(key, window_seconds)


async def get(key: str) -> int:
    """读取计数（不存在为 0）。"""
    return await _get_backend().get(key)


async def delete(*keys: str) -> None:
    """删除计数（用于告警触发后清零）。"""
    await _get_backend().delete(*keys)
