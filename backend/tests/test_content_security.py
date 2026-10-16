"""内容安全（msgSecCheck）测试：放行 / 拦截 / 关闭 / 异常 fail-open / token 刷新重试。

用 monkeypatch 打桩 stable_token 与 msgSecCheck 两个 HTTP 出口，不依赖真实微信接口。
"""
from __future__ import annotations

import os

import httpx
import pymongo
import pytest
from helpers import auth, create_session, login

from app.config import get_settings
from app.db.indexes import COLL_MESSAGES
from app.services import chat, content_security, wechat


def _count_messages(filter_: dict) -> int:
    """同步统计消息数（motor 的 count_documents 返回 Future，同步断言中不可用）。"""
    sync_client = pymongo.MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    try:
        return sync_client[os.environ.get("MONGODB_DB", "xinyu_test")][COLL_MESSAGES].count_documents(filter_)
    finally:
        sync_client.close()


@pytest.fixture()
def fake_llm(monkeypatch):
    async def fake_generate(self, messages, temperature=0.7, max_tokens=1024):
        return "我在听，慢慢来。"

    monkeypatch.setattr(chat.ZhipuProvider, "generate", fake_generate)


class WxStub:
    """微信 HTTP 出口打桩：记录调用次数，按预设返回。"""

    def __init__(self, suggest: str = "pass", errcode: int = 0, check_errcodes: list[int] | None = None):
        self.suggest = suggest
        self.errcode = errcode
        # check_errcodes：按调用次序返回的 errcode 序列（用于 token 失效重试场景）
        self.check_errcodes = list(check_errcodes or [])
        self.token_calls = 0
        self.check_calls = 0
        self.force_refresh_seen: list[bool] = []

    async def token(self, payload: dict) -> dict:
        self.token_calls += 1
        self.force_refresh_seen.append(bool(payload.get("force_refresh")))
        return {"access_token": f"token_{self.token_calls}", "expires_in": 7200}

    async def check(self, token: str, content: str, openid: str) -> dict:
        self.check_calls += 1
        if self.check_errcodes:
            errcode = self.check_errcodes.pop(0)
            return {"errcode": errcode, "errmsg": "stub"}
        return {
            "errcode": self.errcode,
            "errmsg": "stub",
            "result": {"suggest": self.suggest, "label": 100},
        }


def _enable_check(monkeypatch, stub: WxStub, enabled: bool = True) -> None:
    """登录完成后再开启安检：绕过 mock 跳过条件，并打桩两个 HTTP 出口。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "wx_content_check_enabled", enabled)
    monkeypatch.setattr(settings, "wx_mock_login", False)
    monkeypatch.setattr(settings, "wx_appid", "test_appid")
    monkeypatch.setattr(settings, "wx_secret", "test_secret")
    wechat._reset_token_cache()
    monkeypatch.setattr(wechat, "_request_stable_token", stub.token)
    monkeypatch.setattr(content_security, "_request_msg_sec_check", stub.check)


def _send(client, token, sid, content="今天心情还不错"):
    return client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": content, "stream": False},
        headers=auth(token),
    )


def test_check_pass_allows_message(client, db, fake_llm, monkeypatch):
    token = login(client)  # mock 登录须在开启安检前完成
    sid = create_session(client, token)
    stub = WxStub(suggest="pass")
    _enable_check(monkeypatch, stub)

    r = _send(client, token, sid)
    assert r.status_code == 200, r.text
    assert stub.check_calls == 1  # 确实过了安检
    assert _count_messages({"role": "user"}) == 1


def test_check_risky_blocks_message(client, db, fake_llm, monkeypatch):
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub(suggest="risky")
    _enable_check(monkeypatch, stub)

    r = _send(client, token, sid)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == 2006
    # 拦截后不落库（不存违规内容）、不计轮次
    assert _count_messages({}) == 0


def test_check_errcode_87014_blocks(client, db, fake_llm, monkeypatch):
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub(errcode=87014)
    _enable_check(monkeypatch, stub)

    r = _send(client, token, sid)
    assert r.status_code == 422
    assert r.json()["code"] == 2006
    assert _count_messages({}) == 0


def test_check_review_suggest_passes(client, db, fake_llm, monkeypatch):
    """suggest=review 放行：1v1 场景无人审队列，误杀倾诉表达代价更高。"""
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub(suggest="review")
    _enable_check(monkeypatch, stub)

    r = _send(client, token, sid)
    assert r.status_code == 200, r.text


def test_check_disabled_skips_http(client, db, fake_llm, monkeypatch):
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub(suggest="risky")  # 即使打桩为 risky，开关关闭也不应调用
    _enable_check(monkeypatch, stub, enabled=False)

    r = _send(client, token, sid)
    assert r.status_code == 200, r.text
    assert stub.check_calls == 0


def test_check_api_failure_fail_open(client, db, fake_llm, monkeypatch):
    """安检接口异常：fail-open，不阻断对话主链路。"""
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub()

    async def boom(token_, content, openid):
        raise httpx.ConnectError("wx unreachable")

    _enable_check(monkeypatch, stub)
    monkeypatch.setattr(content_security, "_request_msg_sec_check", boom)

    r = _send(client, token, sid)
    assert r.status_code == 200, r.text
    assert _count_messages({"role": "user"}) == 1


def test_token_expired_refreshes_and_retries(client, db, fake_llm, monkeypatch):
    """首次安检返回 token 失效 → 强制刷新 token 重试，最终放行。"""
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub(suggest="pass", check_errcodes=[40001])  # 第一次 40001，之后按 suggest 返回
    _enable_check(monkeypatch, stub)

    r = _send(client, token, sid)
    assert r.status_code == 200, r.text
    assert stub.check_calls == 2
    assert stub.token_calls == 2  # 首次取 token + 失效后强制刷新
    assert stub.force_refresh_seen == [False, True]


def test_token_cache_reused_across_messages(client, db, fake_llm, monkeypatch):
    """token 有效期内缓存复用：两条消息只取一次 token。"""
    token = login(client)
    sid = create_session(client, token)
    stub = WxStub(suggest="pass")
    _enable_check(monkeypatch, stub)

    assert _send(client, token, sid, "第一条").status_code == 200
    assert _send(client, token, sid, "第二条").status_code == 200
    assert stub.check_calls == 2
    assert stub.token_calls == 1
