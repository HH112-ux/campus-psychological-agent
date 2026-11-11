"""P4 隐私与数据权利测试：consent / export / erase。

依赖 MongoDB（通过 conftest 的 client fixture 自动 skip）。
"""
from __future__ import annotations

from tests.helpers import auth, create_session, login


def test_consent(client, db):
    """隐私同意：记录 consent_at + 政策版本。"""
    token = login(client, consent=False)
    # 初始未同意
    resp = client.get("/api/v1/users/me", headers=auth(token))
    assert resp.json()["data"]["consented"] is False

    # 同意
    resp = client.post(
        "/api/v1/users/me/consent",
        json={"agree": True, "policy_version": "1.0"},
        headers=auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["consented"] is True

    # 再次查询已同意
    resp = client.get("/api/v1/users/me", headers=auth(token))
    assert resp.json()["data"]["consented"] is True


def test_consent_reject_disagree(client, db):
    """不同意时返回 400。"""
    token = login(client, consent=False)
    resp = client.post(
        "/api/v1/users/me/consent",
        json={"agree": False},
        headers=auth(token),
    )
    assert resp.status_code == 400


def test_business_routes_require_consent(client, db):
    """B-3：未同意时业务接口一律 403/2007，读取同意状态与同意接口仍可用。"""
    token = login(client, consent=False)
    headers = auth(token)

    # 允许：查看本人信息（前端据此决定是否进同意流程）
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200

    # 拦截：建会话 / 打卡等业务接口
    blocked = client.post("/api/v1/sessions", json={}, headers=headers)
    assert blocked.status_code == 403
    body = blocked.json()
    assert body["code"] == 2007
    assert body["data"]["consent_required"] is True
    assert client.get("/api/v1/emotion/checkins/today", headers=headers).status_code == 403

    # 同意后放行
    client.post(
        "/api/v1/users/me/consent",
        json={"agree": True, "policy_version": "1.0"},
        headers=headers,
    )
    assert client.post("/api/v1/sessions", json={}, headers=headers).status_code == 201


def test_export_data(client, db):
    """数据导出：包含用户/会话/消息/情绪/打卡/风险事件。"""
    token = login(client)
    create_session(client, token)

    # 导出
    resp = client.get("/api/v1/users/me/data/export", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "user" in data
    assert "sessions" in data
    assert "messages" in data
    assert "emotion_records" in data
    assert "checkins" in data
    assert "risk_events" in data
    assert "exported_at" in data
    # 至少有 1 个会话
    assert len(data["sessions"]) >= 1


def test_erase_requires_confirm_text(client, db):
    """删除数据必须输入"删除"确认。"""
    token = login(client)
    resp = client.request(
        "DELETE",
        "/api/v1/users/me/data",
        json={"confirm_text": "确认删除"},
        headers=auth(token),
    )
    assert resp.status_code == 400


def test_erase_soft_delete(client, db):
    """软删后用户不再可见，令牌失效。"""
    token = login(client)
    create_session(client, token)

    resp = client.request(
        "DELETE",
        "/api/v1/users/me/data",
        json={"confirm_text": "删除"},
        headers=auth(token),
    )
    assert resp.status_code == 200
    assert "erase_at" in resp.json()["data"]
    assert "recover_deadline" in resp.json()["data"]

    # 用旧 token 访问 /me → 401（用户已软删）
    resp = client.get("/api/v1/users/me", headers=auth(token))
    assert resp.status_code == 401


def test_erase_isolates_other_users(client, db):
    """删除用户 A 的数据不影响用户 B。"""
    token_a = login(client, "mock_user_a")
    token_b = login(client, "mock_user_b")
    create_session(client, token_a)
    create_session(client, token_b)

    # 删除 A
    client.request(
        "DELETE",
        "/api/v1/users/me/data",
        json={"confirm_text": "删除"},
        headers=auth(token_a),
    )
    # B 仍正常
    resp = client.get("/api/v1/users/me", headers=auth(token_b))
    assert resp.status_code == 200


def test_purge_expired_data(client, db):
    """M3：恢复期未满不清理，到期后 purge_expired_data 物理删除该用户全部数据。

    purge 的调用点在 main.lifespan 的定时任务里（G7），此处直接调用其任务体，
    经 client.portal 在应用事件循环内执行，验证「承诺可兑现」而非仅「函数存在」。
    """
    from datetime import timedelta

    from app.core.timeutil import now_cst
    from app.db.indexes import (
        COLL_CHECKINS,
        COLL_EMOTION_RECORDS,
        COLL_MESSAGES,
        COLL_RISK_EVENTS,
        COLL_SESSIONS,
        COLL_USERS,
    )
    from app.db.mongo import mongo
    from app.services.privacy import purge_expired_data

    openid = "mock_purge_user"
    token = login(client, openid)
    create_session(client, token)

    # 走行权接口软删（erase_at 默认落在恢复期之后）
    resp = client.request(
        "DELETE",
        "/api/v1/users/me/data",
        json={"confirm_text": "删除"},
        headers=auth(token),
    )
    assert resp.status_code == 200

    async def _expire_and_purge():
        user = await mongo.db[COLL_USERS].find_one({"openid": openid})
        assert user is not None and user.get("deleted_at") is not None
        uid = user["_id"]
        session_ids = [
            s["_id"]
            async for s in mongo.db[COLL_SESSIONS].find({"user_id": uid}, {"_id": 1})
        ]
        assert session_ids, "前置：软删用户应仍持有会话，消息删除路径才被覆盖"
        # 造一条消息，验证消息集合随会话一并物理删除
        await mongo.db[COLL_MESSAGES].insert_one({
            "session_id": session_ids[0],
            "role": "user",
            "content": "purge-test",
            "created_at": now_cst(),
        })

        # 1) 恢复期未满：不应被物理删除
        purged_before = await purge_expired_data()

        # 2) 把 erase_at 调到过去，模拟已过恢复期
        await mongo.db[COLL_USERS].update_one(
            {"_id": uid},
            {"$set": {"erase_at": now_cst() - timedelta(seconds=1)}},
        )
        purged_after = await purge_expired_data()

        remaining = {
            "users": await mongo.db[COLL_USERS].count_documents({"_id": uid}),
            "sessions": await mongo.db[COLL_SESSIONS].count_documents({"user_id": uid}),
            "messages": await mongo.db[COLL_MESSAGES].count_documents(
                {"session_id": {"$in": session_ids}}
            ),
            "emotions": await mongo.db[COLL_EMOTION_RECORDS].count_documents({"user_id": uid}),
            "checkins": await mongo.db[COLL_CHECKINS].count_documents({"user_id": uid}),
            "risk_events": await mongo.db[COLL_RISK_EVENTS].count_documents({"user_id": uid}),
        }
        return purged_before, purged_after, remaining

    purged_before, purged_after, remaining = client.portal.call(_expire_and_purge)
    assert purged_before == 0, "恢复期未满不应被物理删除"
    assert purged_after == 1, "到期用户应被物理删除且计数为 1"
    assert all(v == 0 for v in remaining.values()), remaining


def test_purge_scheduler_starts_without_db_connection(monkeypatch):
    """P2：调度器创建不得依赖启动瞬间 Mongo 已连通。

    慢启动 / 瞬时不可达时若跳过创建，「软删 N 天后物理删除」将永远不执行；
    调度器自身循环已有失败重试，因此前置条件只应看配置开关。
    """
    import asyncio

    from app import main as main_module
    from app.config import get_settings

    started = []

    async def _fake_purge():
        started.append("purge")
        await asyncio.Event().wait()

    async def _fake_caring():
        await asyncio.Event().wait()

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setitem(get_settings().__dict__, "data_purge_enabled", True)
    monkeypatch.setitem(get_settings().__dict__, "caring_enabled", True)
    monkeypatch.setattr(main_module.mongo, "connect", _noop)
    monkeypatch.setattr(main_module.mongo, "disconnect", _noop)
    monkeypatch.setattr(
        type(main_module.mongo), "is_connected", property(lambda self: False)
    )
    monkeypatch.setattr(main_module.privacy_svc, "run_purge_scheduler", _fake_purge)
    monkeypatch.setattr(main_module.caring_svc, "run_caring_scheduler", _fake_caring)
    monkeypatch.setattr(main_module, "close_redis_client", _noop)

    async def _run() -> None:
        async with main_module.lifespan(None):
            assert main_module.mongo.is_connected is False, "前置：模拟启动瞬间 DB 未连通"
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert started == ["purge"]
