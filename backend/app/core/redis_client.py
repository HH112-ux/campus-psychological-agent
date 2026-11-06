"""Redis 客户端单例（延迟创建；限流与跨实例冷却/计数共用连接池）。

由 `core/ratelimit.py` 与 `core/counter.py` 共享，避免两套连接与两套 URL 解析。
"""
from __future__ import annotations

import logging
from contextlib import suppress

from app.config import get_settings

logger = logging.getLogger(__name__)

_client = None


async def get_client():
    """返回 Redis 异步客户端单例（首次调用时按配置创建）。"""
    global _client
    if _client is None:
        # 延迟导入：memory 后端（dev/CI）不引入 redis 运行时依赖
        import redis.asyncio as aioredis

        _client = aioredis.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _client


async def close_client() -> None:
    """关闭连接（lifespan 停机时调用）。"""
    global _client
    if _client is not None:
        with suppress(Exception):
            await _client.aclose()
        _client = None
