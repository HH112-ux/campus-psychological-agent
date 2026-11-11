"""测试通用 helper（普通函数，配合 conftest 的 client fixture 使用）。"""
from __future__ import annotations


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, mock_openid: str | None = None, consent: bool = True) -> str:
    """mock 登录并返回 access_token；可临时指定 openid 制造第二个用户。

    默认在登录后完成隐私同意（B-3：业务接口要求 consent_at）；需要验证未同意态时
    传 consent=False。

    指定 openid 时会临时改写全局 wx_mock_openid（Settings 为进程内单例），
    该改写由 conftest 的 _restore_settings 夹具在每个用例结束后统一还原，
    不会泄漏到后续用例。
    """
    if mock_openid is not None:
        from app.config import get_settings
        get_settings().wx_mock_openid = mock_openid
    resp = client.post("/api/v1/auth/wx-login", json={"code": "mock-code"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    if consent:
        agreed = client.post(
            "/api/v1/users/me/consent",
            json={"agree": True, "policy_version": "1.0"},
            headers=auth(token),
        )
        assert agreed.status_code == 200, agreed.text
    return token


def create_session(client, token: str) -> str:
    resp = client.post("/api/v1/sessions", json={}, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["session_id"]
