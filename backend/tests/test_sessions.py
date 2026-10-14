"""P1 会话管理测试：CRUD、并发上限、跨用户隔离（不暴露存在性）。"""
from __future__ import annotations

from helpers import auth, create_session, login


def test_session_crud_flow(client, db):
    token = login(client)
    sid = create_session(client, token)

    # 列表
    lst = client.get("/api/v1/sessions", headers=auth(token)).json()["data"]
    assert lst["total"] == 1 and lst["items"][0]["session_id"] == sid

    # 重命名
    r = client.patch(f"/api/v1/sessions/{sid}", json={"title": "我的烦恼"}, headers=auth(token))
    assert r.status_code == 200 and r.json()["data"]["title"] == "我的烦恼"

    # 详情
    d = client.get(f"/api/v1/sessions/{sid}", headers=auth(token)).json()["data"]
    assert d["rounds"] == 0 and d["messages"] == []

    # 删除
    assert client.delete(f"/api/v1/sessions/{sid}", headers=auth(token)).status_code == 200
    assert client.get("/api/v1/sessions", headers=auth(token)).json()["data"]["total"] == 0


def test_concurrency_limit(client, db):
    """并发会话上限：达到 session_concurrency_limit 后创建被拒 2003。"""
    from app.config import get_settings

    limit = get_settings().session_concurrency_limit
    token = login(client)
    for _ in range(limit):
        create_session(client, token)
    r = client.post("/api/v1/sessions", json={}, headers=auth(token))
    assert r.status_code == 429
    assert r.json()["code"] == 2003


def test_cross_user_returns_404(client, db, monkeypatch):
    from app.config import get_settings

    token_a = login(client)
    sid_a = create_session(client, token_a)

    # 切换到另一个微信用户
    monkeypatch.setattr(get_settings(), "wx_mock_openid", "mock_other_user")
    token_b = login(client)

    r = client.get(f"/api/v1/sessions/{sid_a}", headers=auth(token_b))
    assert r.status_code == 404
    assert r.json()["code"] in (2001, 2005)  # 不暴露资源存在性


def test_nonexistent_session_404(client, db):
    token = login(client)
    r = client.get("/api/v1/sessions/6acd9bda621bd486b71376e1", headers=auth(token))
    assert r.status_code == 404 and r.json()["code"] == 2001
