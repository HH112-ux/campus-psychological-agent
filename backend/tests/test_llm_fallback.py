"""E2 多模型容灾测试：FallbackProvider + 工厂函数 get_chat_provider / get_light_provider。

- FallbackProvider.generate：主成功 / 主失败切备 / 双失败抛主异常；
- FallbackProvider.stream：主完全失败 → 整段切备；主已产出部分 → 重抛（不拼接两段回复）；
- app.llm 工厂：qwen_enabled=false 返回裸 Zhipu；true 且 key 非空返回 FallbackProvider；
- chat / emotion / long_memory 模块名 ZhipuProvider 仍然存在（保留给既有 monkeypatch）。
- 全部不依赖 MongoDB / Redis / 真实 LLM。
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.llm import get_chat_provider, get_light_provider
from app.llm.base import LLMProvider
from app.llm.fallback import FallbackProvider
from app.llm.qwen import QwenProvider
from app.llm.zhipu import ZhipuProvider


class _OkProvider(LLMProvider):
    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply

    async def generate(self, messages, temperature=0.7, max_tokens=1024):
        return self.reply

    async def stream(self, messages, temperature=0.7, max_tokens=1024):
        for c in self.reply:
            yield c


class _BoomProvider(LLMProvider):
    def __init__(self, exc: Exception = RuntimeError("boom")) -> None:
        self.exc = exc

    async def generate(self, messages, temperature=0.7, max_tokens=1024):
        raise self.exc

    async def stream(self, messages, temperature=0.7, max_tokens=1024):
        raise self.exc
        yield  # pragma: no cover — 保持 async generator 契约


# ---------- FallbackProvider.generate ----------

def test_generate_primary_success_no_fallback():
    fb = FallbackProvider(primary=_OkProvider("primary"), backup=_BoomProvider())
    result = asyncio.run(fb.generate([]))
    assert result == "primary"


def test_generate_primary_fail_falls_back():
    fb = FallbackProvider(primary=_BoomProvider(), backup=_OkProvider("backup"))
    result = asyncio.run(fb.generate([]))
    assert result == "backup"


def test_generate_both_fail_raises_primary_exc():
    fb = FallbackProvider(
        primary=_BoomProvider(RuntimeError("primary boom")),
        backup=_BoomProvider(ValueError("backup boom")),
    )
    with pytest.raises(RuntimeError, match="primary boom"):
        asyncio.run(fb.generate([]))


# ---------- FallbackProvider.stream ----------

def test_stream_primary_produces_all():
    fb = FallbackProvider(primary=_OkProvider("abc"), backup=_OkProvider("xyz"))
    chunks = asyncio.run(_collect(fb.stream([])))
    assert chunks == ["a", "b", "c"]


def test_stream_primary_partial_then_raises_RERAISES_not_concats():
    """主已产出部分再失败 → 重抛让 chat.py 保留部分；禁止拼接两段独立 LLM 回复。"""
    partial_primary = _OkProvider("abc")

    async def _halfway_stream(messages, temperature=0.7, max_tokens=1024):
        yield "a"
        yield "b"
        raise RuntimeError("stream boom")

    partial_primary.stream = _halfway_stream  # type: ignore[method-assign]
    fb = FallbackProvider(primary=partial_primary, backup=_OkProvider("XY"))
    with pytest.raises(RuntimeError, match="stream boom"):
        asyncio.run(_collect(fb.stream([])))


def test_stream_primary_never_produces_switches_to_backup():
    """主 provider 从未产出就抛 → 整个备用 provider 接管。"""
    fb = FallbackProvider(primary=_BoomProvider(), backup=_OkProvider("xyz"))
    chunks = asyncio.run(_collect(fb.stream([])))
    assert chunks == ["x", "y", "z"]


def test_stream_both_fail_raises_primary_exc():
    fb = FallbackProvider(
        primary=_BoomProvider(RuntimeError("primary")),
        backup=_BoomProvider(ValueError("backup")),
    )
    with pytest.raises(RuntimeError, match="primary"):
        asyncio.run(_collect(fb.stream([])))


async def _collect(stream):
    return [c async for c in stream]


# ---------- 工厂函数 ----------

def test_get_chat_provider_no_qwen_is_plain_zhipu(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_enabled", False)
    monkeypatch.setattr(get_settings(), "qwen_api_key", "")
    p = get_chat_provider()
    assert isinstance(p, ZhipuProvider)
    assert not isinstance(p, FallbackProvider)


def test_get_chat_provider_qwen_enabled_wraps_fallback(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_enabled", True)
    monkeypatch.setattr(get_settings(), "qwen_api_key", "sk-test")
    p = get_chat_provider()
    assert isinstance(p, FallbackProvider)


def test_get_chat_provider_qwen_enabled_but_key_empty_is_plain(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_enabled", True)
    monkeypatch.setattr(get_settings(), "qwen_api_key", "")
    p = get_chat_provider()
    assert isinstance(p, ZhipuProvider)


def test_get_light_provider_also_switches(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_enabled", True)
    monkeypatch.setattr(get_settings(), "qwen_api_key", "sk-test")
    p = get_light_provider()
    assert isinstance(p, FallbackProvider)
    # 关掉 → 裸 Zhipu
    monkeypatch.setattr(get_settings(), "qwen_enabled", False)
    p2 = get_light_provider()
    assert isinstance(p2, ZhipuProvider)


# ---------- chat / emotion / long_memory 模块名 ZhipuProvider 仍存在 ----------

def test_services_keep_zhipu_module_name_for_patching():
    import app.services.chat as chat
    import app.services.emotion as emotion_svc
    import app.services.long_memory as lm_svc

    for mod in (chat, emotion_svc, lm_svc):
        assert hasattr(mod, "ZhipuProvider"), f"{mod.__name__} 缺少 ZhipuProvider 模块名"
        assert mod.ZhipuProvider is ZhipuProvider


# ---------- QwenProvider 基本契约（不打真实 API） ----------

def test_qwen_provider_defaults_to_chat_model(monkeypatch):
    monkeypatch.setattr(get_settings(), "qwen_model_chat", "qwen-plus")
    monkeypatch.setattr(get_settings(), "qwen_api_key", "sk-dummy")
    monkeypatch.setattr(get_settings(), "qwen_base_url", "https://test")
    q = QwenProvider()
    assert q.model == "qwen-plus"
    q2 = QwenProvider(model="qwen-turbo")
    assert q2.model == "qwen-turbo"
