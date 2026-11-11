"""B-6 危机链路与 DB 解耦：读库/写库失败时仍能给出内置热线，不再 500。"""
from __future__ import annotations

import asyncio

import pytest
from bson import ObjectId

from app.db.mongo import mongo
from app.services import chat, crisis
from app.services.crisis_data import FALLBACK_RESOURCES, LEVEL1_PHRASES
from tests import helpers


class _BrokenCollection:
    async def find_one(self, *args, **kwargs):
        raise RuntimeError("mongo down")

    async def insert_one(self, *args, **kwargs):
        raise RuntimeError("mongo down")

    def find(self, *args, **kwargs):
        raise RuntimeError("mongo down")


class _BrokenDb:
    def __getitem__(self, name):
        return _BrokenCollection()


@pytest.fixture(autouse=True)
def _reset_lexicon_cache():
    yield
    # 用例内缓存的是「内置词表」结果，测试结束后置失效，避免污染其他用例
    crisis.refresh_lexicon_cache()


def _run(coro):
    return asyncio.run(coro)


def _break_db(monkeypatch):
    monkeypatch.setattr(mongo, "_db", _BrokenDb())


def test_lexicon_falls_back_to_builtin_when_db_errors(monkeypatch):
    _break_db(monkeypatch)
    crisis.refresh_lexicon_cache()
    l1, _ = _run(crisis._load_lexicon())
    assert l1 == sorted(set(LEVEL1_PHRASES))


def test_get_resources_falls_back_when_db_errors(monkeypatch):
    _break_db(monkeypatch)
    assert _run(crisis.get_resources()) == FALLBACK_RESOURCES


def test_record_risk_event_does_not_raise_when_db_errors(monkeypatch):
    _break_db(monkeypatch)
    # 不抛异常即通过：审计写入失败只记日志，不阻断求助链路
    _run(crisis.record_risk_event(ObjectId(), ObjectId(), "mid", ["测试词"]))


def test_handle_detection_still_returns_hotline_when_db_errors(monkeypatch):
    _break_db(monkeypatch)
    crisis.refresh_lexicon_cache()
    session = {"_id": ObjectId(), "user_id": ObjectId(), "crisis_score": 0}

    result, payload, _ = _run(crisis.handle_detection("我想死", session))

    assert result.level == "high"
    assert payload is not None and payload["show_card"] is True
    assert payload["resources"] == FALLBACK_RESOURCES["resources"]


def test_send_message_degrades_to_hotline_when_prepare_fails(client, db, monkeypatch):
    token = helpers.login(client)
    session_id = helpers.create_session(client, token)

    async def _boom(*args, **kwargs):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(chat, "prepare_turn", _boom)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "我今天有点累", "stream": False},
        headers=helpers.auth(token),
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["degraded"] is True
    assert data["crisis"]["show_card"] is True
    assert data["crisis"]["resources"]


def test_stream_send_degrades_to_hotline_when_prepare_fails(client, db, monkeypatch):
    token = helpers.login(client)
    session_id = helpers.create_session(client, token)

    async def _boom(*args, **kwargs):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(chat, "prepare_turn", _boom)
    resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "我今天有点累", "stream": True},
        headers=helpers.auth(token),
    )

    assert resp.status_code == 200
    assert "event: crisis" in resp.text
    assert "event: done" in resp.text
