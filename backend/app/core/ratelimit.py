"""应用层限流：内存 / Redis 两种后端（滑动窗口日志）。

- 策略：登录 10 次/分钟/IP、消息 30 条/小时/用户、读 60 次/分钟/用户（对齐 API 文档第 12 节）。
- 后端：
  - memory（默认）：进程内滑动日志，单机/dev/测试使用；
  - redis（生产多实例）：ZSET 滑动窗口 + Lua 原子判定（被拒请求不占窗口），
    计数跨实例共享（M5/G4）。Redis 不可达时 fail-open（告警依赖 M5 监控），
    不因限流基础设施故障阻断对话主链路。
- 切换：RATELIMIT_BACKEND=redis + REDIS_URL，无需改业务代码。
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from contextlib import suppress
from typing import Protocol

from app.config import get_settings
from app.core.exceptions import CODE_RATE_LIMITED, BizError

logger = logging.getLogger(__name__)

# Lua：原子「清除窗口外记录 → 判定 → 放行才写入并续期」；返回 1=放行，0=拒绝
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window) + 1)
return 1
"""


class RateLimitBackend(Protocol):
    async def check(self, key: str, limit: int, window_seconds: float) -> None:
        """记一次命中；窗口内已达 limit 则抛 429。"""
        ...


class MemoryBackend:
    """进程内滑动窗口日志（单调时钟）。"""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    def reset(self) -> None:
        self._hits.clear()

    async def check(self, key: str, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        arr = self._hits[key]
        cutoff = now - window_seconds
        while arr and arr[0] < cutoff:
            arr.pop(0)
        if len(arr) >= limit:
            raise BizError(CODE_RATE_LIMITED, "操作太频繁，请稍后再试", http_status=429)
        arr.append(now)


class RedisBackend:
    """Redis ZSET 滑动窗口（Lua 原子判定，跨实例共享）。"""

    async def check(self, key: str, limit: int, window_seconds: float) -> None:
        member = f"{time.time():.6f}-{uuid.uuid4().hex[:12]}"
        try:
            client = await _get_redis_client()
            allowed = await client.eval(
                _SLIDING_WINDOW_LUA,
                1,
                key,
                str(time.time()),
                str(window_seconds),
                str(limit),
                member,
            )
        except Exception:
            # fail-open：限流基础设施故障不应阻断主链路（生产由 M5 监控告警发现）
            logger.warning("Redis 限流不可达，本轮放行（fail-open）", exc_info=True)
            return
        if not allowed:
            raise BizError(CODE_RATE_LIMITED, "操作太频繁，请稍后再试", http_status=429)


_memory_backend = MemoryBackend()
_backend: RateLimitBackend | None = None
_redis_client = None


async def _get_redis_client():
    """Redis 客户端单例（延迟创建；连接池复用）。"""
    global _redis_client
    if _redis_client is None:
        # 延迟导入：memory 后端（dev/CI）不引入 redis 运行时依赖
        import redis.asyncio as aioredis

        _redis_client = aioredis.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _redis_client


async def close_redis_client() -> None:
    """关闭 Redis 连接（lifespan 停机时调用）。"""
    global _redis_client
    if _redis_client is not None:
        with suppress(Exception):
            await _redis_client.aclose()
        _redis_client = None


def _get_backend() -> RateLimitBackend:
    global _backend
    if _backend is None:
        _backend = (
            RedisBackend()
            if get_settings().ratelimit_backend.lower() == "redis"
            else _memory_backend
        )
    return _backend


def reset_all() -> None:
    """清空限流计数与后端缓存（仅供测试使用；不断开 Redis 连接）。"""
    global _backend
    _memory_backend.reset()
    _backend = None


async def hit_login_rate(ip: str) -> None:
    await _get_backend().check(f"login:{ip}", 10, 60)


async def hit_message_rate(user_id: str) -> None:
    limit = get_settings().user_message_hourly_limit
    await _get_backend().check(f"message:{user_id}", limit, 3600)


async def hit_read_rate(user_id: str) -> None:
    await _get_backend().check(f"read:{user_id}", 60, 60)
