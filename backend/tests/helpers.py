"""测试通用 helper（普通函数，配合 conftest 的 client fixture 使用）。"""
from __future__ import annotations


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, mock_openid: str | None = None) -> str:
    """mock 登录并返回 access_token；可临时指定 openid 制造第二个用户。"""
    if mock_openid is not None:
        from app.config import get_settings
        get_settings().wx_mock_openid = mock_openid
    resp = client.post("/api/v1/auth/wx-login", json={"code": "mock-code"})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def create_session(client, token: str) -> str:
    resp = client.post("/api/v1/sessions", json={}, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["session_id"]
