"""B-4 会话标题加密：落库为密文，接口/导出返回明文。"""
from __future__ import annotations

import asyncio
import base64
import os
import secrets

import pymongo
import pytest

from app.config import get_settings
from app.core import crypto
from app.db.indexes import COLL_SESSIONS
from app.db.mongo import mongo
from app.db.oid import parse_oid
from tests import helpers


@pytest.fixture()
def encryption_key(monkeypatch):
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    monkeypatch.setitem(get_settings().__dict__, "data_encryption_key", key)
    crypto._aesgcm = None
    crypto._disabled = False
    yield key
    crypto._aesgcm = None
    crypto._disabled = False


@pytest.fixture()
def sync_db(db):
    """直连 pymongo 读原始文档（motor 的调用返回绑定事件循环的 Future，同步断言里无法用）。"""
    client = pymongo.MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    yield client[os.environ.get("MONGODB_DB", "xinyu_test")]
    client.close()


def test_first_message_title_encrypted_at_rest(client, sync_db, encryption_key):
    token = helpers.login(client)
    session_id = helpers.create_session(client, token)
    text = "我不想活了，最近真的撑不住"

    resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": text, "stream": False},
        headers=helpers.auth(token),
    )
    assert resp.status_code == 200

    raw = sync_db[COLL_SESSIONS].find_one({"_id": parse_oid(session_id)})
    assert crypto.is_encrypted(raw["title"])
    assert text[:12] not in str(raw)

    detail = client.get(f"/api/v1/sessions/{session_id}", headers=helpers.auth(token))
    assert detail.json()["data"]["title"] == text[:12]


def test_create_and_rename_title_encrypted_return_plaintext(client, sync_db, encryption_key):
    token = helpers.login(client)

    created = client.post(
        "/api/v1/sessions", json={"title": "自带标题"}, headers=helpers.auth(token)
    )
    assert created.status_code == 201
    assert created.json()["data"]["title"] == "自带标题"
    session_id = created.json()["data"]["session_id"]
    raw = sync_db[COLL_SESSIONS].find_one({"_id": parse_oid(session_id)})
    assert crypto.is_encrypted(raw["title"])

    renamed = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "考试压力"},
        headers=helpers.auth(token),
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["title"] == "考试压力"
    raw = sync_db[COLL_SESSIONS].find_one({"_id": parse_oid(session_id)})
    assert crypto.is_encrypted(raw["title"])

    listed = client.get("/api/v1/sessions", headers=helpers.auth(token)).json()["data"]
    assert listed["items"][0]["title"] == "考试压力"


def test_export_returns_decrypted_title(client, db, encryption_key):
    token = helpers.login(client)
    session_id = helpers.create_session(client, token)
    client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "家庭关系"},
        headers=helpers.auth(token),
    )

    export = client.get("/api/v1/users/me/data/export", headers=helpers.auth(token))
    assert export.status_code == 200
    titles = [s["title"] for s in export.json()["data"]["sessions"]]
    assert "家庭关系" in titles


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._i]
        self._i += 1
        return doc


class _FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        assert "title" in query
        return _FakeCursor(
            [d for d in self.docs if isinstance(d.get("title"), str) and d["title"] != ""]
        )

    async def update_one(self, flt, update):
        for d in self.docs:
            if d["_id"] == flt["_id"]:
                d.update(update["$set"])


class _FakeDb:
    def __init__(self, docs):
        self.docs = docs

    def __getitem__(self, name):
        return _FakeCollection(self.docs)


def test_migration_dry_run_and_idempotent(monkeypatch, encryption_key):
    """历史明文标题迁移：dry-run 只统计不写；实跑后密文；重复执行为 0。"""
    from scripts.migrate_encrypt_sensitive_fields import _migrate_text_field

    docs = [
        {"_id": 1, "title": "旧明文标题"},
        {"_id": 2, "title": crypto.encrypt("已加密")},
        {"_id": 3, "title": None},
    ]
    monkeypatch.setattr(mongo, "_db", _FakeDb(docs))

    assert asyncio.run(_migrate_text_field(COLL_SESSIONS, "title", True)) == 1
    assert docs[0]["title"] == "旧明文标题"  # dry-run 不落盘

    assert asyncio.run(_migrate_text_field(COLL_SESSIONS, "title", False)) == 1
    assert crypto.is_encrypted(docs[0]["title"])
    assert crypto.decrypt(docs[0]["title"]) == "旧明文标题"
    assert docs[2]["title"] is None  # 空值原样保留

    assert asyncio.run(_migrate_text_field(COLL_SESSIONS, "title", False)) == 0
