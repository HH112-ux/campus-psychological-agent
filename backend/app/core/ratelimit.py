"""应用层内存限流（固定窗口）。

单机内测期使用：登录 10 次/分钟/IP、消息 30 条/小时/用户（对齐 API 文档第 12 节）。
多进程/多实例部署时需替换为 Redis 等共享计数；Nginx 层另做 IP 限流。
"""
from __future__ import annotations

import time
from collections import defaultdict

from app.config import get_settings
from app.core.exceptions import CODE_RATE_LIMITED, BizError

_hits: dict[str, list[float]] = defaultdict(list)


def reset_all() -> None:
    """清空全部限流计数（仅供测试使用）。"""
    _hits.clear()


async def _check(key: str, limit: int, window_seconds: float) -> None:
    now = time.monotonic()
    arr = _hits[key]
    cutoff = now - window_seconds
    while arr and arr[0] < cutoff:
        arr.pop(0)
    if len(arr) >= limit:
        raise BizError(CODE_RATE_LIMITED, "操作太频繁，请稍后再试", http_status=429)
    arr.append(now)


async def hit_login_rate(ip: str) -> None:
    await _check(f"login:{ip}", 10, 60)


async def hit_message_rate(user_id: str) -> None:
    limit = get_settings().user_message_hourly_limit
    await _check(f"message:{user_id}", limit, 3600)


async def hit_read_rate(user_id: str) -> None:
    await _check(f"read:{user_id}", 60, 60)
