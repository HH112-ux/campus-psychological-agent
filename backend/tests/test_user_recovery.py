"""B-9：软删用户再次微信登录的身份语义。

- 恢复期内（erase_at 未到）登录：接回同一身份，会话一并恢复，is_new=False；
- 超过恢复期：先物理删除旧身份全部数据，再以同一 openid 注册新身份（is_new=True）；
- 并发首登同一 openid：唯一索引冲突不得冒泡成 500。

依赖 MongoDB（通过 conftest 的 client fixture 自动 skip）。
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from bson import ObjectId

from app.core.timeutil import now_cst
from app.db.indexes import COLL_SESSIONS, COLL_USERS
from app.db.mongo import mongo
from tests.helpers import auth, create_session, login


@pytest.fixture(autouse=True)
def _users_openid_unique_index(client, db):
    """复现生产 schema：openid 唯一索引由 scripts/init_db.py 建立，测试库默认不建。

    B-9 的 500 正来自该索引冲突，缺失索引会让用例失真。
    """

    async def _create() -> None:
        await mongo.db[COLL_USERS].create_index([("openid", 1)], unique=True)

    client.portal.call(_create)


def _erase(client, token: str) -> None:
    resp = client.request(
        "DELETE",
        "/api/v1/users/me/data",
        json={"confirm_text": "删除"},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text


def _wx_login(client):
    return client.post("/api/v1/auth/wx-login", json={"code": "mock-code"})


def test_relogin_within_recover_window_restores_same_user(client, db):
    """恢复期内再次登录：修复前因 openid 唯一索引冲突直接 500。"""
    token = login(client, "mock_recover_user")
    session_id = create_session(client, token)
    user_id = client.get("/api/v1/users/me", headers=auth(token)).json()["data"]["user_id"]
    _erase(client, token)

    resp = _wx_login(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["is_new"] is False
    assert data["consented"] is True, "同意状态应随身份一并恢复，不应要求重复同意"

    new_token = data["access_token"]
    me = client.get("/api/v1/users/me", headers=auth(new_token))
    assert me.status_code == 200
    assert me.json()["data"]["user_id"] == user_id

    sessions = client.get("/api/v1/sessions", headers=auth(new_token)).json()["data"]
    assert [s["session_id"] for s in sessions["items"]] == [session_id], "会话应随身份恢复"


def test_relogin_after_recover_window_creates_new_identity(client, db):
    """超过恢复期：旧身份物理删除，按同一 openid 注册全新身份。"""
    token = login(client, "mock_expired_user")
    create_session(client, token)
    old_user_id = client.get("/api/v1/users/me", headers=auth(token)).json()["data"]["user_id"]
    _erase(client, token)

    async def _expire() -> None:
        await mongo.db[COLL_USERS].update_one(
            {"openid": "mock_expired_user"},
            {"$set": {"erase_at": now_cst() - timedelta(seconds=1)}},
        )

    client.portal.call(_expire)

    resp = _wx_login(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["is_new"] is True
    assert data["consented"] is False, "新身份不应继承旧身份的隐私同意"

    new_token = data["access_token"]
    me = client.get("/api/v1/users/me", headers=auth(new_token)).json()["data"]
    assert me["user_id"] != old_user_id
    # 新身份需重新同意隐私政策，之后名下不应继承旧会话
    agreed = client.post(
        "/api/v1/users/me/consent",
        json={"agree": True, "policy_version": "1.0"},
        headers=auth(new_token),
    )
    assert agreed.status_code == 200
    sessions = client.get("/api/v1/sessions", headers=auth(new_token)).json()["data"]
    assert sessions["total"] == 0

    async def _assert_old_gone() -> None:
        old_id = ObjectId(old_user_id)
        assert await mongo.db[COLL_USERS].count_documents({"_id": old_id}) == 0
        assert await mongo.db[COLL_SESSIONS].count_documents({"user_id": old_id}) == 0

    client.portal.call(_assert_old_gone)


def test_concurrent_first_login_same_openid(client, db):
    """并发首登同一 openid：所有请求应拿到同一身份，且只有一个新建。"""
    from app.services.users import get_or_create_by_openid

    async def _race():
        return await asyncio.gather(
            *[get_or_create_by_openid("mock_race_user") for _ in range(5)]
        )

    results = client.portal.call(_race)
    assert len({str(u["_id"]) for u, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1
