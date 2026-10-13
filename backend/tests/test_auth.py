"""P1 认证链路测试：mock 微信登录、JWT、refresh 旋转、me、鉴权。"""
from __future__ import annotations

from helpers import auth, login


def test_wx_login_issues_tokens(client, db):
    from app.config import get_settings
    get_settings().wx_mock_openid = "mock_test_user"
    resp = client.post("/api/v1/auth/wx-login", json={"code": "any-code"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["expires_in"] == 604800
    assert "openid" not in resp.text


def test_me_requires_and_returns_user(client, db):
    token = login(client)
    resp = client.get("/api/v1/users/me", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user_id"]
    assert data["consented"] is False
    assert "openid" not in data


def test_missing_token_rejected(client, db):
    resp = client.get("/api/v1/sessions")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1002


def test_refresh_rotation_invalidates_old(client, db):
    from app.config import get_settings
    get_settings().wx_mock_openid = "mock_test_user"
    login_resp = client.post("/api/v1/auth/wx-login", json={"code": "c"})
    old_rt = login_resp.json()["data"]["refresh_token"]

    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_rt})
    assert r1.status_code == 200
    new_rt = r1.json()["data"]["refresh_token"]

    # 旧 refresh_token 已旋转，立即作废
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_rt})
    assert r2.status_code == 401
    assert r2.json()["code"] == 1003

    # 新 refresh_token 可用
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": new_rt})
    assert r3.status_code == 200
