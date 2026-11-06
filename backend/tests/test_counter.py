"""W3 跨实例共享状态测试：`core/counter` 冷却/计数双后端 + `core/metrics` 失败率。

告警冷却表与失败率计数原为进程内全局变量，多实例部署下各算各的（重复推送 / 分母
永远凑不齐）。现统一走 `core/counter`（`shared_state_backend` 切换 memory/redis 双后端）。

- memory 后端：冷却窗口、清除、计数（不依赖 Redis）；
- redis 后端：FakeRedis 契约（SET NX EX / INCR+EXPIRE Lua 原子化 / GET / DELETE）；
- Redis 不可达：fail-open（冷却放行、计数降级为 0、清理静默）；
- FailRateCounter：≥min_samples 且失败率超阈值 → 告警并清零（重新观察）。

这些用例不依赖 MongoDB，任何环境都会执行。
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from app.config import get_settings
from app.core import counter
from app.core.metrics import FailRateCounter


class FakeRedis:
    """复刻 RedisCounter 用到的命令语义（SET NX EX / INCR+EXPIRE Lua / GET / DELETE）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expires: dict[str, int] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    async def get(self, key):
        return self.store.get(key)

    async def eval(self, script, numkeys, *args):
        """复刻 _INCR_WITH_TTL_LUA 语义：INCR 后仅首次（值==1）设置 EXPIRE，原子。"""
        key, ttl = args[0], args[1]
        val = int(self.store.get(key, "0")) + 1
        self.store[key] = str(val)
        if val == 1:
            self.expires[key] = ttl
        return val

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed


class BoomRedis:
    """任何命令都抛连接异常，用于验证 fail-open。"""

    async def set(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")

    async def get(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")

    async def eval(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")

    async def delete(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")


def _patch_backend(monkeypatch, backend: str) -> None:
    monkeypatch.setattr(get_settings(), "shared_state_backend", backend)
    counter.reset_all()


@pytest.fixture()
def redis_backend(monkeypatch):
    """把 RedisCounter 的客户端替换为 FakeRedis（存活于 core.redis_client 命名空间）。"""
    import app.core.redis_client as redis_client

    fake = FakeRedis()

    async def get_client():
        return fake

    _patch_backend(monkeypatch, "redis")
    monkeypatch.setattr(redis_client, "get_client", get_client)
    yield fake
    counter.reset_all()


# ---------- memory 后端 ----------

def test_memory_cooldown_allows_then_blocks(monkeypatch):
    _patch_backend(monkeypatch, "memory")

    async def run():
        assert await counter.cooldown_allows("c", 600) is True  # 首次放行
        assert await counter.cooldown_allows("c", 600) is False  # 窗口内冷却
        await counter.clear("c")  # 「失败不占冷却」语义
        assert await counter.cooldown_allows("c", 600) is True

    asyncio.run(run())
    counter.reset_all()


def test_memory_counter_incr_get_delete(monkeypatch):
    _patch_backend(monkeypatch, "memory")

    async def run():
        assert await counter.incr("n", 60) == 1
        assert await counter.incr("n", 60) == 2
        assert await counter.get("n") == 2
        await counter.delete("n")
        assert await counter.get("n") == 0

    asyncio.run(run())
    counter.reset_all()


# ---------- redis 后端（FakeRedis 契约） ----------

def test_redis_cooldown_uses_set_nx_ex(redis_backend):
    async def run():
        assert await counter.cooldown_allows("c", 600) is True
        assert redis_backend.store["c"] == "1"  # SET NX 占位
        assert redis_backend.expires["c"] == 600  # EX 窗口
        assert await counter.cooldown_allows("c", 600) is False  # NX 已存在
        await counter.clear("c")
        assert "c" not in redis_backend.store
        assert await counter.cooldown_allows("c", 600) is True

    asyncio.run(run())


def test_redis_counter_incr_sets_ttl_once(redis_backend):
    async def run():
        assert await counter.incr("n", 60) == 1
        assert redis_backend.expires["n"] == 60  # 首次 INCR 设置 TTL
        assert await counter.incr("n", 60) == 2
        assert redis_backend.expires["n"] == 60  # 后续不自重置 TTL
        assert await counter.get("n") == 2
        await counter.delete("n")
        assert await counter.get("n") == 0

    asyncio.run(run())


def test_redis_unreachable_fail_open(monkeypatch):
    import app.core.redis_client as redis_client

    async def boom_client():
        return BoomRedis()

    _patch_backend(monkeypatch, "redis")
    monkeypatch.setattr(redis_client, "get_client", boom_client)

    async def run():
        # 冷却放行（不阻断主链路）、计数降级为 0、清理静默不抛错
        assert await counter.cooldown_allows("c", 600) is True
        assert await counter.incr("n", 60) == 0
        assert await counter.get("n") == 0
        await counter.clear("c")
        await counter.delete("n")

    asyncio.run(run())
    counter.reset_all()


# ---------- FailRateCounter（失败率监控） ----------

def test_fail_rate_alerts_only_when_over_threshold(monkeypatch, caplog):
    _patch_backend(monkeypatch, "memory")
    frc = FailRateCounter("test_metric", min_samples=20, threshold=0.05)

    async def run():
        # 19 成功 + 1 失败 = 20 样本、失败率恰好 5% → 未「超过」阈值，不告警
        for _ in range(19):
            await frc.success()
        await frc.failure()
        # 再 1 次失败 → 21 样本 / 2 失败 ≈ 9.5% > 5% → 告警
        await frc.failure()

    with caplog.at_level(logging.WARNING, logger="app.core.metrics"):
        asyncio.run(run())

    assert "test_metric" in caplog.text
    # 告警后清零，重新观察
    assert asyncio.run(counter.get("metric:test_metric:total")) == 0
    assert asyncio.run(counter.get("metric:test_metric:fail")) == 0
    counter.reset_all()


def test_fail_rate_below_min_samples_silent(monkeypatch, caplog):
    _patch_backend(monkeypatch, "memory")
    frc = FailRateCounter("small_metric", min_samples=20, threshold=0.05)

    async def run():
        # 样本不足 min_samples：即使全失败也不告警
        for _ in range(19):
            await frc.failure()

    with caplog.at_level(logging.WARNING, logger="app.core.metrics"):
        asyncio.run(run())

    assert "small_metric" not in caplog.text
    assert asyncio.run(counter.get("metric:small_metric:total")) == 19
    counter.reset_all()
