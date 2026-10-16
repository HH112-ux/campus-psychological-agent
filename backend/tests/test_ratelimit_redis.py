"""限流后端测试：内存后端选择 + Redis 后端语义（Lua 契约）+ fail-open + 真 Redis 集成。

- 不依赖真实 Redis 的用例：FakeRedisZSet 复刻 Lua 脚本语义，验证 Python 侧调用契约；
- 真 Redis 集成用例：仅在设置 REDIS_TEST_URL 时运行（CI 的 backend job 挂 redis service）。
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.config import get_settings
from app.core import ratelimit
from app.core.exceptions import BizError


class FakeRedisZSet:
    """内存 ZSET，语义与 ratelimit._SLIDING_WINDOW_LUA 完全一致（只用于验证调用契约）。"""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}

    async def eval(self, script, numkeys, key, now_s, window_s, limit_s, member):
        now = float(now_s)
        window = float(window_s)
        limit = int(limit_s)
        z = self.zsets.setdefault(key, {})
        cutoff = now - window
        for m in [m for m, score in z.items() if score <= cutoff]:
            del z[m]
        if len(z) >= limit:
            return 0
        z[member] = now
        return 1

    async def aclose(self) -> None:
        pass


class BoomRedis:
    async def eval(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")


@pytest.fixture()
def redis_backend(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ratelimit_backend", "redis")
    fake = FakeRedisZSet()

    async def get_client():
        return fake

    monkeypatch.setattr(ratelimit, "_get_redis_client", get_client)
    ratelimit.reset_all()
    yield fake
    ratelimit.reset_all()


def test_factory_selects_backend(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ratelimit_backend", "memory")
    ratelimit.reset_all()
    assert isinstance(ratelimit._get_backend(), ratelimit.MemoryBackend)

    monkeypatch.setattr(settings, "ratelimit_backend", "redis")
    ratelimit.reset_all()
    assert isinstance(ratelimit._get_backend(), ratelimit.RedisBackend)
    ratelimit.reset_all()


def test_redis_allows_until_limit(client, redis_backend):
    async def run():
        backend = ratelimit.RedisBackend()
        for _ in range(3):
            await backend.check("k", 3, 60)
        with pytest.raises(BizError) as exc:
            await backend.check("k", 3, 60)
        assert exc.value.http_status == 429
        assert len(redis_backend.zsets["k"]) == 3  # 被拒请求不写入、不占窗口

    client.portal.call(run)


def test_redis_window_expiry(client, redis_backend):
    async def run():
        backend = ratelimit.RedisBackend()
        await backend.check("w", 1, 0.3)
        with pytest.raises(BizError):
            await backend.check("w", 1, 0.3)
        await asyncio.sleep(0.35)
        await backend.check("w", 1, 0.3)  # 窗口外记录已清除，放行

    client.portal.call(run)


def test_redis_keys_independent(client, redis_backend):
    async def run():
        backend = ratelimit.RedisBackend()
        await backend.check("a", 1, 60)
        await backend.check("b", 1, 60)  # 不同 key 各自计数
        with pytest.raises(BizError):
            await backend.check("a", 1, 60)

    client.portal.call(run)


def test_redis_rejected_does_not_consume_window(client, redis_backend):
    async def run():
        backend = ratelimit.RedisBackend()
        for _ in range(2):
            await backend.check("k", 2, 60)
        for _ in range(3):
            with pytest.raises(BizError):
                await backend.check("k", 2, 60)
        assert len(redis_backend.zsets["k"]) == 2  # 连续拒绝后窗口内仍是 2 条

    client.portal.call(run)


def test_redis_failure_fail_open(client, redis_backend, monkeypatch):
    async def boom_client():
        return BoomRedis()

    monkeypatch.setattr(ratelimit, "_get_redis_client", boom_client)

    async def run():
        # Redis 不可达不抛错、不阻断主链路
        for _ in range(5):
            await ratelimit.RedisBackend().check("k", 1, 60)

    client.portal.call(run)


def test_hit_message_rate_uses_redis_backend(client, redis_backend):
    async def run():
        # 与对外契约一致：30 条/小时/用户（设置值），第 31 条 429
        for _ in range(get_settings().user_message_hourly_limit):
            await ratelimit.hit_message_rate("u-redis")
        with pytest.raises(BizError) as exc:
            await ratelimit.hit_message_rate("u-redis")
        assert exc.value.http_status == 429

    client.portal.call(run)


REDIS_TEST_URL = os.getenv("REDIS_TEST_URL")


@pytest.mark.skipif(not REDIS_TEST_URL, reason="未设置 REDIS_TEST_URL，跳过真 Redis 集成测试")
def test_real_redis_integration(client, monkeypatch):
    import redis.asyncio as aioredis

    settings = get_settings()
    monkeypatch.setattr(settings, "ratelimit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", REDIS_TEST_URL)
    ratelimit.reset_all()

    key = f"login:test-{uuid.uuid4().hex}"

    async def run():
        r = aioredis.Redis.from_url(REDIS_TEST_URL, decode_responses=True)
        await r.ping()
        await r.delete(key)
        backend = ratelimit.RedisBackend()
        try:
            for _ in range(10):
                await backend.check(key, 10, 60)
            with pytest.raises(BizError):
                await backend.check(key, 10, 60)
            # TTL 已设置（窗口 + 1s），key 不会永久残留
            ttl = await r.ttl(key)
            assert 0 < ttl <= 61
        finally:
            await r.delete(key)
            await r.aclose()
            await ratelimit.close_redis_client()

    client.portal.call(run)
