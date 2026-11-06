"""E3 模型路由与成本基线测试。

- select_tier：开关关闭 / 危机 / 负面情绪 / 长文本 一律主档；短句+平静 → 轻量档；
- provider_for_tier：light 档取 E2 的 light provider（主备映射同样生效）；
- cost：累计与快照、关闭开关时不记录；
- chat 集成：路由开启且短句平静时，流式链路实际调用轻量档并记录成本。
全部不依赖 MongoDB / Redis / 真实 LLM。
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.core import cost
from app.llm import router
from app.llm.base import LLMProvider
from app.llm.fallback import FallbackProvider
from app.services.crisis import CrisisResult


def _enable_routing(monkeypatch, enabled: bool = True) -> None:
    monkeypatch.setattr(get_settings(), "cost_routing_enabled", enabled)


# ---------- select_tier ----------

def test_routing_disabled_always_chat(monkeypatch):
    _enable_routing(monkeypatch, False)
    assert router.select_tier("嗯", "none", "calm") == router.TIER_CHAT


def test_short_calm_no_crisis_uses_light(monkeypatch):
    _enable_routing(monkeypatch)
    monkeypatch.setattr(get_settings(), "cost_routing_light_max_chars", 30)
    assert router.select_tier("我有点想家", "none", None) == router.TIER_LIGHT


def test_crisis_forces_chat(monkeypatch):
    _enable_routing(monkeypatch)
    assert router.select_tier("嗯", "mid", "calm") == router.TIER_CHAT
    assert router.select_tier("嗯", "high", "calm") == router.TIER_CHAT


@pytest.mark.parametrize("emotion", ["anxious", "depressed", "angry"])
def test_negative_emotion_forces_chat(monkeypatch, emotion):
    _enable_routing(monkeypatch)
    assert router.select_tier("嗯", "none", emotion) == router.TIER_CHAT


def test_neutral_emotion_keeps_light(monkeypatch):
    _enable_routing(monkeypatch)
    for emotion in ("calm", "ok", "other", None):
        assert router.select_tier("嗯", "none", emotion) == router.TIER_LIGHT


def test_long_content_forces_chat(monkeypatch):
    _enable_routing(monkeypatch)
    monkeypatch.setattr(get_settings(), "cost_routing_light_max_chars", 5)
    assert router.select_tier("这是一段明显更长的倾诉内容", "none", "calm") == router.TIER_CHAT


def test_whitespace_stripped_before_length_check(monkeypatch):
    _enable_routing(monkeypatch)
    monkeypatch.setattr(get_settings(), "cost_routing_light_max_chars", 3)
    assert router.select_tier("  嗯  ", "none", "calm") == router.TIER_LIGHT


# ---------- provider_for_tier ----------

def test_provider_for_tier_light_is_light_provider(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(router, "get_light_provider", lambda: sentinel)
    assert router.provider_for_tier(router.TIER_LIGHT) is sentinel


def test_provider_for_tier_chat_is_chat_provider(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(router, "get_chat_provider", lambda: sentinel)
    assert router.provider_for_tier(router.TIER_CHAT) is sentinel


def test_select_chat_provider_returns_tier_and_provider(monkeypatch):
    _enable_routing(monkeypatch)
    sentinel = object()
    monkeypatch.setattr(router, "get_light_provider", lambda: sentinel)
    provider, tier = router.select_chat_provider("嗯", "none", "calm")
    assert tier == router.TIER_LIGHT and provider is sentinel


# ---------- cost ----------

def test_cost_record_and_snapshot(monkeypatch):
    monkeypatch.setattr(get_settings(), "cost_tracking_enabled", True)
    cost.reset()
    cost.record_call("chat", 100, 20)
    cost.record_call("chat", 50, 10)
    cost.record_call("light", 10, 5)
    snap = cost.snapshot()
    assert snap["chat"] == {"calls": 2, "prompt_chars": 150, "completion_chars": 30}
    assert snap["light"] == {"calls": 1, "prompt_chars": 10, "completion_chars": 5}


def test_cost_disabled_does_not_record(monkeypatch):
    monkeypatch.setattr(get_settings(), "cost_tracking_enabled", False)
    cost.reset()
    cost.record_call("chat", 100, 20)
    assert cost.snapshot() == {}


def test_cost_negative_chars_clamped(monkeypatch):
    monkeypatch.setattr(get_settings(), "cost_tracking_enabled", True)
    cost.reset()
    cost.record_call("chat", -5, -3)
    assert cost.snapshot()["chat"] == {"calls": 1, "prompt_chars": 0, "completion_chars": 0}


# ---------- chat 集成 ----------

class _FakeLightProvider(LLMProvider):
    used = False

    async def generate(self, messages, temperature=0.7, max_tokens=1024):
        type(self).used = True
        return "在的"

    async def stream(self, messages, temperature=0.7, max_tokens=1024):
        type(self).used = True
        yield "在"
        yield "的"


def _drain_stream(turn):
    """收集真流式增量（首块前失败时降级）。"""

    async def _run():
        import app.services.chat as chat

        chunks: list[str] = []
        degraded = False
        try:
            async for delta in chat._stream_deltas(turn):
                chunks.append(delta)
        except chat._StreamUnavailable:
            degraded = True
        return chunks, degraded

    return asyncio.run(_run())


def test_chat_stream_uses_light_provider_when_routing_enabled(monkeypatch):
    import app.services.chat as chat

    _enable_routing(monkeypatch)
    monkeypatch.setattr(get_settings(), "cost_tracking_enabled", True)
    cost.reset()
    _FakeLightProvider.used = False

    async def _fake_build(turn):
        return []

    monkeypatch.setattr(chat, "_build_messages", _fake_build)
    monkeypatch.setattr(router, "get_light_provider", lambda: _FakeLightProvider())

    turn = chat.Turn(
        user={"_id": "u"},
        session={"_id": "s"},
        content="嗯",
        user_message_id="mid",
        crisis=CrisisResult(),
    )
    chunks, degraded = _drain_stream(turn)
    assert degraded is False and "".join(chunks) == "在的"
    assert _FakeLightProvider.used is True
    assert cost.snapshot()["light"]["calls"] == 1


def test_chat_stream_uses_chat_provider_when_routing_disabled(monkeypatch):
    import app.services.chat as chat

    _enable_routing(monkeypatch, False)
    monkeypatch.setattr(get_settings(), "cost_tracking_enabled", True)
    cost.reset()
    _FakeLightProvider.used = False

    async def _fake_build(turn):
        return []

    monkeypatch.setattr(chat, "_build_messages", _fake_build)
    monkeypatch.setattr(router, "get_light_provider", lambda: _FakeLightProvider())
    monkeypatch.setattr(
        chat.ZhipuProvider, "stream", _fake_chat_stream, raising=True
    )

    turn = chat.Turn(
        user={"_id": "u"},
        session={"_id": "s"},
        content="嗯",
        user_message_id="mid",
        crisis=CrisisResult(),
    )
    chunks, degraded = _drain_stream(turn)
    assert degraded is False and "".join(chunks) == "主档"
    assert _FakeLightProvider.used is False
    assert cost.snapshot()["chat"]["calls"] == 1


async def _fake_chat_stream(self, messages, temperature=0.7, max_tokens=1024):
    yield "主"
    yield "档"


def test_stream_deltas_are_forwarded_lazily(monkeypatch):
    """真流式：首块在模型生成结束前就已交给消费方，而不是先收齐再一次性下发。"""
    import app.services.chat as chat

    _enable_routing(monkeypatch, False)
    state = {"first_consumed": False}

    async def fake_stream(self, messages, temperature=0.7, max_tokens=1024):
        yield "第一块"
        # 生成器恢复时，消费方必须已经处理过首块（否则说明是「先收齐再下发」）
        assert state["first_consumed"] is True
        yield "第二块。"

    async def _fake_build(turn):
        return []

    monkeypatch.setattr(chat, "_build_messages", _fake_build)
    monkeypatch.setattr(chat.ZhipuProvider, "stream", fake_stream, raising=True)

    turn = chat.Turn(
        user={"_id": "u"},
        session={"_id": "s"},
        content="嗯",
        user_message_id="mid",
        crisis=CrisisResult(),
    )

    async def _run():
        chunks: list[str] = []
        async for delta in chat._stream_deltas(turn):
            chunks.append(delta)
            state["first_consumed"] = True
        return chunks

    assert asyncio.run(_run()) == ["第一块", "第二块。"]


def test_fallback_provider_still_wraps_light_tier(monkeypatch):
    """轻量档同样享受 E2 主备容灾（工厂返回 FallbackProvider）。"""
    monkeypatch.setattr(get_settings(), "qwen_enabled", True)
    monkeypatch.setattr(get_settings(), "qwen_api_key", "sk-test")
    provider = router.provider_for_tier(router.TIER_LIGHT)
    assert isinstance(provider, FallbackProvider)


# ---------- _build_messages → 情绪路由（chat.py 取错键的回归用例）----------
def _patch_build_deps(monkeypatch, chat, latest):
    async def _fake_window(session_id):
        return []

    async def _fake_injection(user_id, content):
        return []

    async def _fake_latest(session_id):
        return latest

    monkeypatch.setattr(chat.memory, "load_window", _fake_window)
    monkeypatch.setattr(chat.long_memory, "build_injection", _fake_injection)
    monkeypatch.setattr(chat.emotion_svc, "latest_session_emotion", _fake_latest)
    monkeypatch.setattr(
        chat, "build_system_prompt", lambda latest_emotion=None, memories=None: ""
    )


def test_build_messages_reads_emotion_type_for_routing(monkeypatch):
    """latest_session_emotion 的标签在 "type"；取 "emotion" 会让分流恒走轻量档。"""
    import app.services.chat as chat

    _enable_routing(monkeypatch)
    _patch_build_deps(
        monkeypatch,
        chat,
        {"type": "depressed", "intensity": 3, "evidence": "", "risk_level": "none"},
    )
    turn = chat.Turn(
        user={"_id": "u"},
        session={"_id": "s"},
        content="嗯",
        user_message_id="mid",
        crisis=CrisisResult(),
    )
    asyncio.run(chat._build_messages(turn))

    assert turn.latest_emotion == "depressed"
    assert router.select_tier("嗯", "none", turn.latest_emotion) == router.TIER_CHAT


def test_build_messages_without_emotion_record_stays_none(monkeypatch):
    """无历史情绪记录时不误判为负面情绪。"""
    import app.services.chat as chat

    _enable_routing(monkeypatch)
    _patch_build_deps(monkeypatch, chat, None)
    turn = chat.Turn(
        user={"_id": "u"},
        session={"_id": "s"},
        content="嗯",
        user_message_id="mid",
        crisis=CrisisResult(),
    )
    asyncio.run(chat._build_messages(turn))

    assert turn.latest_emotion is None
    assert router.select_tier("嗯", "none", turn.latest_emotion) == router.TIER_LIGHT
