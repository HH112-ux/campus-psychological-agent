"""P1 消息链路测试：非流式/流式、危机拦截不走模型、降级、轮次、长度。

用 monkeypatch 替换 ZhipuProvider，避免真实调用大模型。
"""
from __future__ import annotations

import pytest
from helpers import auth, create_session, login

from app.services import chat


@pytest.fixture()
def fake_llm(monkeypatch):
    async def fake_generate(self, messages, temperature=0.7, max_tokens=1024):
        return "我在听，慢慢来，先做一个深呼吸。"

    async def fake_stream(self, messages, temperature=0.7, max_tokens=1024):
        for piece in ["我在听，", "慢慢来。"]:
            yield piece

    monkeypatch.setattr(chat.ZhipuProvider, "generate", fake_generate)
    monkeypatch.setattr(chat.ZhipuProvider, "stream", fake_stream)


def _send(client, token, sid, content, stream=False):
    return client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": content, "stream": stream},
        headers=auth(token),
    )


def test_nonstream_normal_reply(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    r = _send(client, token, sid, "最近有点焦虑")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["assistant_reply"] == "我在听，慢慢来，先做一个深呼吸。"
    assert d["risk_level"] == "none"
    assert d["crisis"] is None
    assert d["degraded"] is False


def test_stream_frame_sequence(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    r = _send(client, token, sid, "你好呀", stream=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "event: meta" in body
    assert "event: delta" in body
    assert "慢慢来" in body
    assert "event: done" in body
    assert "event: crisis" not in body  # 正常消息不发危机事件


def test_high_crisis_bypasses_llm(client, db, monkeypatch):
    calls = {"n": 0}

    async def boom_generate(self, messages, temperature=0.7, max_tokens=1024):
        calls["n"] += 1
        raise RuntimeError("高危命中时不应调用大模型")

    monkeypatch.setattr(chat.ZhipuProvider, "generate", boom_generate)

    token = login(client)
    sid = create_session(client, token)
    r = _send(client, token, sid, "我不想活了")
    d = r.json()["data"]
    assert d["risk_level"] == "high"
    assert d["crisis"]["level"] == "high"
    assert d["crisis"]["show_card"] is True
    assert len(d["crisis"]["resources"]) >= 3
    assert calls["n"] == 0  # 确认未调用大模型


def test_model_failure_degrades(client, db, monkeypatch):
    async def boom_generate(self, messages, temperature=0.7, max_tokens=1024):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr(chat.ZhipuProvider, "generate", boom_generate)

    token = login(client)
    sid = create_session(client, token)
    d = _send(client, token, sid, "最近睡不好").json()["data"]
    assert d["degraded"] is True
    assert d["assistant_reply"] == chat.DEGRADED_REPLY


def test_rounds_increment_and_title(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    _send(client, token, sid, "第一条想说的话")
    _send(client, token, sid, "第二条")
    detail = client.get(f"/api/v1/sessions/{sid}", headers=auth(token)).json()["data"]
    assert detail["rounds"] == 2
    assert len(detail["messages"]) == 4  # 每轮 user + assistant
    # 标题由首条消息前 12 字回填
    assert detail["title"].startswith("第一条想说的话")


def test_empty_and_too_long_content(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    r1 = _send(client, token, sid, "   ")
    assert r1.status_code == 422 and r1.json()["code"] == 2004
    r2 = _send(client, token, sid, "x" * 2001)
    assert r2.status_code == 422 and r2.json()["code"] == 2004


def test_dislike_requires_reason(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    _send(client, token, sid, "你好")
    detail = client.get(f"/api/v1/sessions/{sid}", headers=auth(token)).json()["data"]
    assistant_id = [m for m in detail["messages"] if m["role"] == "assistant"][0]["message_id"]
    r = client.post(
        f"/api/v1/messages/{assistant_id}/feedback",
        json={"rating": "dislike"},
        headers=auth(token),
    )
    assert r.status_code == 400 and r.json()["code"] == 5001
