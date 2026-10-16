"""监控告警 MVP 测试（M5 ③ / M4 值班人通知链路）。

覆盖：
- send_alert：开关/未配 URL 只记日志、webhook 载荷格式、冷却去抖、异常不抛出；
- 隐私红线：告警内容不含命中词与对话原文；
- crisis 挂点：high 触发值班人通知、mid 不触发、模型兜底追加漏报信号；
- chat 挂点：LLM 重试失败降级时触发告警。
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from bson import ObjectId

from app.config import get_settings
from app.services import alerting
from app.services import chat as chat_svc
from app.services import crisis as crisis_svc


class _FakeResp:
    def raise_for_status(self) -> None:
        return None


class _FakeHttp:
    """httpx.AsyncClient 打桩：记录 post 调用，可注入异常。"""

    calls: list[tuple[str, dict]] = []
    error: Exception | None = None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> _FakeHttp:
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, json: dict) -> _FakeResp:
        _FakeHttp.calls.append((url, json))
        if _FakeHttp.error is not None:
            raise _FakeHttp.error
        return _FakeResp()


@pytest.fixture()
def alert_env(monkeypatch):
    """开启告警 + 配置 webhook + 打桩 HTTP 出口；每个用例前清冷却与调用记录。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_enabled", True)
    monkeypatch.setattr(settings, "alert_webhook_url", "https://qyapi.weixin.qq.com/bot/send?key=test")
    monkeypatch.setattr(settings, "alert_cooldown_seconds", 600)
    monkeypatch.setattr(alerting.httpx, "AsyncClient", _FakeHttp)
    _FakeHttp.calls = []
    _FakeHttp.error = None
    alerting.reset_cooldowns()
    yield settings
    alerting.reset_cooldowns()


def _run(coro):
    return asyncio.run(coro)


# ---------- send_alert 基础行为 ----------

def test_alert_disabled_only_logs(alert_env, caplog):
    """alert_enabled=false：不发 webhook，但仍记 warning 日志。"""
    alert_env.alert_enabled = False
    with caplog.at_level(logging.WARNING, logger="app.services.alerting"):
        _run(alerting.send_alert("k1", "标题", ["行1"]))
    assert _FakeHttp.calls == []
    assert "k1" in caplog.text and "标题" in caplog.text


def test_alert_no_webhook_url_only_logs(alert_env, caplog):
    """未配置 webhook URL（dev 默认）：不发请求，只记日志。"""
    alert_env.alert_webhook_url = ""
    with caplog.at_level(logging.WARNING, logger="app.services.alerting"):
        _run(alerting.send_alert("k1", "标题", ["行1"]))
    assert _FakeHttp.calls == []
    assert "k1" in caplog.text


def test_alert_posts_wecom_webhook(alert_env):
    """配置 webhook 后按企业微信机器人格式发送，内容含标题与各行。"""
    _run(alerting.send_alert("k1", "高危风险信号", ["用户: u1", "会话: s1"]))
    assert len(_FakeHttp.calls) == 1
    url, payload = _FakeHttp.calls[0]
    assert url.startswith("https://qyapi.weixin.qq.com/")
    assert payload["msgtype"] == "text"
    content = payload["text"]["content"]
    assert "高危风险信号" in content and "用户: u1" in content and "会话: s1" in content


def test_alert_cooldown_dedupes_webhook(alert_env):
    """同一 key 冷却期内只发一次 webhook；清冷却后可再发。"""
    _run(alerting.send_alert("k1", "t", ["a"]))
    _run(alerting.send_alert("k1", "t", ["b"]))
    assert len(_FakeHttp.calls) == 1
    # 不同 key 不受同 key 冷却影响
    _run(alerting.send_alert("k2", "t", ["c"]))
    assert len(_FakeHttp.calls) == 2
    alerting.reset_cooldowns()
    _run(alerting.send_alert("k1", "t", ["d"]))
    assert len(_FakeHttp.calls) == 3


def test_alert_webhook_failure_never_raises(alert_env, caplog):
    """webhook 异常只记日志、永不抛出（告警是旁路，不得阻断主链路）。"""
    _FakeHttp.error = RuntimeError("网络不可达")
    with caplog.at_level(logging.ERROR, logger="app.services.alerting"):
        _run(alerting.send_alert("k1", "t", ["a"]))  # 不应抛出
    assert "webhook 发送失败" in caplog.text


# ---------- crisis 挂点 ----------

def test_high_risk_event_notifies_oncall(client, db, alert_env):
    """record_risk_event level=high → 通知值班人；内容只含 ID/触发源，不含命中词。"""
    uid, sid = ObjectId(), ObjectId()
    client.portal.call(
        crisis_svc.record_risk_event, uid, sid, "high", ["敏感命中词XYZ"], "lexicon"
    )
    assert len(_FakeHttp.calls) == 1
    content = _FakeHttp.calls[0][1]["text"]["content"]
    assert str(uid) in content and str(sid) in content and "lexicon" in content
    # 隐私红线：命中词不得出现在告警中
    assert "敏感命中词XYZ" not in content


def test_mid_risk_event_no_alert(client, db, alert_env):
    """record_risk_event level=mid → 不通知值班人。"""
    client.portal.call(crisis_svc.record_risk_event, ObjectId(), ObjectId(), "mid", ["w"], "lexicon")
    assert _FakeHttp.calls == []


def test_model_risk_sends_lexicon_miss_signal(client, db, alert_env):
    """handle_model_risk：高危通知 + 词库漏报信号（模型兜底命中而词库未命中）。"""
    uid, sid = ObjectId(), ObjectId()
    client.portal.call(crisis_svc.handle_model_risk, uid, sid, "模型证据")
    contents = [c[1]["text"]["content"] for c in _FakeHttp.calls]
    assert any("高危风险信号" in c and "model" in c for c in contents)
    assert any("词库漏报信号" in c for c in contents)


# ---------- chat 挂点 ----------

def test_llm_degraded_triggers_alert(monkeypatch, alert_env):
    """非流式 LLM 重试仍失败 → 降级话术 + 告警。"""

    class _FailProvider:
        async def generate(self, *args, **kwargs):
            raise RuntimeError("模型超时")

    async def _fake_build(turn):
        return []

    monkeypatch.setattr(chat_svc, "_build_messages", _fake_build)
    monkeypatch.setattr(chat_svc, "ZhipuProvider", _FailProvider)

    turn = chat_svc.Turn(
        user={"_id": ObjectId()},
        session={"_id": ObjectId()},
        content="你好",
        user_message_id="mid",
        crisis=crisis_svc.CrisisResult(),
    )
    text, degraded = _run(chat_svc._generate_nonstream(turn))
    assert degraded is True and text == chat_svc.DEGRADED_REPLY
    assert len(_FakeHttp.calls) == 1
    assert "LLM 调用降级" in _FakeHttp.calls[0][1]["text"]["content"]
