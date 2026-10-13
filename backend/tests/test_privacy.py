"""P4 隐私与数据权利测试：consent / export / erase。

依赖 MongoDB（通过 conftest 的 client fixture 自动 skip）。
"""
from __future__ import annotations

from tests.helpers import auth, create_session, login


def test_consent(client, db):
    """隐私同意：记录 consent_at + 政策版本。"""
    token = login(client)
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
    token = login(client)
    resp = client.post(
        "/api/v1/users/me/consent",
        json={"agree": False},
        headers=auth(token),
    )
    assert resp.status_code == 400


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
