"""P5 降级开关测试：流式可关、情绪分析可关。

开关通过 settings 单例字段控制（.env 环境变量），测试用 monkeypatch 覆盖。
"""
from __future__ import annotations

import pytest
from helpers import auth, create_session, login

from app.config import get_settings
from app.services import chat
from app.services import emotion as emotion_svc


@pytest.fixture()
def fake_llm(monkeypatch):
    async def fake_generate(self, messages, temperature=0.7, max_tokens=1024):
        return "我在听，慢慢来。"

    async def fake_stream(self, messages, temperature=0.7, max_tokens=1024):
        yield "我在听，"
        yield "慢慢来。"

    monkeypatch.setattr(chat.ZhipuProvider, "generate", fake_generate)
    monkeypatch.setattr(chat.ZhipuProvider, "stream", fake_stream)


def test_stream_disabled_forces_nonstream(client, db, fake_llm, monkeypatch):
    """stream_enabled=false 时，即使请求 stream=true 也返回 JSON 而非 SSE。"""
    monkeypatch.setattr(get_settings(), "stream_enabled", False)
    token = login(client)
    sid = create_session(client, token)
    r = client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": "你好", "stream": True},
        headers=auth(token),
    )
    assert r.status_code == 200
    assert not r.headers["content-type"].startswith("text/event-stream")
    assert r.json()["data"]["assistant_reply"] == "我在听，慢慢来。"


def test_emotion_disabled_skips_records(client, db, fake_llm, monkeypatch):
    """emotion_analysis_enabled=false 时，不写情绪记录、回复不带 emotion。"""
    monkeypatch.setattr(get_settings(), "emotion_analysis_enabled", False)
    token = login(client)
    sid = create_session(client, token)

    async def fake_analyze(*args, **kwargs):
        raise AssertionError("情绪分析开关关闭后不应被调用")

    monkeypatch.setattr(emotion_svc, "analyze_turn", fake_analyze)

    r = client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": "最近有点焦虑", "stream": False},
        headers=auth(token),
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["emotion"] is None
    assert d["assistant_reply"] == "我在听，慢慢来。"
