"""V3 主动关怀测试：触发检测 / 文案红线 / 频控与授权门槛 / 扫描发送 / 用户开关接口。

DB 集成部分依赖 MongoDB（conftest 的 client fixture 在本地未启动时自动 skip）。
"""
from __future__ import annotations

from datetime import timedelta

from app.config import get_settings
from app.core.timeutil import now_cst
from app.db.indexes import COLL_CARE_MESSAGES, COLL_CHECKINS, COLL_USERS
from app.db.mongo import mongo
from app.services import caring
from tests.helpers import auth, login

_TODAY = "2026-10-19"


# ---------- 触发检测（纯逻辑） ----------

def test_trigger_low_streak():
    """连续 3 天负面档位 → low_streak。"""
    docs = [
        {"date": "2026-10-19", "mood": "low"},
        {"date": "2026-10-18", "mood": "anxious"},
        {"date": "2026-10-17", "mood": "irritable"},
    ]
    assert caring._evaluate_trigger(docs, _TODAY) == "low_streak"


def test_trigger_low_streak_broken_by_positive_day():
    """连续段被正面档位打断 → 不触发 low_streak。"""
    docs = [
        {"date": "2026-10-19", "mood": "low"},
        {"date": "2026-10-18", "mood": "calm"},
        {"date": "2026-10-17", "mood": "low"},
    ]
    assert caring._evaluate_trigger(docs, _TODAY) is None


def test_trigger_checkin_gap():
    """有历史打卡但最近一次已隔 ≥2 天 → checkin_gap。"""
    docs = [{"date": "2026-10-14", "mood": "ok"}]
    assert caring._evaluate_trigger(docs, _TODAY) == "checkin_gap"


def test_trigger_none_without_records():
    """无打卡记录 → 不触发（不对冷用户打扰）。"""
    assert caring._evaluate_trigger([], _TODAY) is None


def test_trigger_none_recent_ok_checkin():
    """今天刚打过卡且状态尚可 → 不触发。"""
    docs = [{"date": "2026-10-19", "mood": "ok"}]
    assert caring._evaluate_trigger(docs, _TODAY) is None


# ---------- 文案红线 ----------

def test_greeting_copy_gentle_and_short():
    """问候语不超过微信 thing 字段 20 字符上限，且不使用说教/命令句式。"""
    forbidden = ("必须", "应该", "一定", "你要", "赶紧", "快点", "不许")
    for text in caring._GREETINGS.values():
        assert len(text) <= 20, text
        assert not any(w in text for w in forbidden), text


# ---------- 扫描与发送（DB 集成） ----------

def _seed_streak(openid: str, *, quota: int, opt_out: bool = False, sent_records: int = 0):
    """造一个候选用户：连续 3 天低落 + 订阅配额，可选预置已发送留档/关闭开关。"""

    async def _run():
        user = await mongo.db[COLL_USERS].find_one({"openid": openid})
        uid = user["_id"]
        await mongo.db[COLL_USERS].update_one(
            {"_id": uid}, {"$set": {"care_subscribe_count": quota, "caring_opt_out": opt_out}}
        )
        today = now_cst().date()
        for i in range(3):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            await mongo.db[COLL_CHECKINS].insert_one(
                {"user_id": uid, "date": d, "mood": "low", "created_at": now_cst()}
            )
        for _ in range(sent_records):
            await mongo.db[COLL_CARE_MESSAGES].insert_one(
                {"user_id": uid, "kind": "low_streak", "status": "sent", "created_at": now_cst()}
            )
        return uid

    return _run


def test_scan_sends_and_decrements_quota(client, db, monkeypatch):
    """触发 + 有配额 + 模板已配置 → 发送成功、扣减配额、留档 status=sent。"""
    login(client, "caring_user")
    monkeypatch.setattr(get_settings(), "wx_subscribe_template_id", "TPL_TEST")
    uid = client.portal.call(_seed_streak("caring_user", quota=1))

    stats = client.portal.call(caring.run_caring_scan)
    assert stats == {"scanned": 1, "sent": 1, "skipped": 0, "failed": 0}

    async def _verify():
        u = await mongo.db[COLL_USERS].find_one({"_id": uid})
        recs = await mongo.db[COLL_CARE_MESSAGES].find({"user_id": uid}).to_list(length=10)
        return u, recs

    user, recs = client.portal.call(_verify)
    assert user["care_subscribe_count"] == 0
    assert len(recs) == 1 and recs[0]["status"] == "sent" and recs[0]["kind"] == "low_streak"


def test_scan_skips_without_template(client, db, monkeypatch):
    """未配置订阅模板 ID → fail-safe 跳过，不发送、不扣配额。"""
    login(client, "caring_user")
    monkeypatch.setattr(get_settings(), "wx_subscribe_template_id", "")
    uid = client.portal.call(_seed_streak("caring_user", quota=1))

    stats = client.portal.call(caring.run_caring_scan)
    assert stats == {"scanned": 0, "sent": 0, "skipped": 0, "failed": 0}

    async def _count():
        return await mongo.db[COLL_USERS].find_one({"_id": uid})

    assert client.portal.call(_count)["care_subscribe_count"] == 1


def test_scan_frequency_cap(client, db, monkeypatch):
    """本周已发满 2 条（频控上限）→ 触发但跳过。"""
    login(client, "caring_user")
    monkeypatch.setattr(get_settings(), "wx_subscribe_template_id", "TPL_TEST")
    client.portal.call(_seed_streak("caring_user", quota=1, sent_records=2))

    stats = client.portal.call(caring.run_caring_scan)
    assert stats["sent"] == 0 and stats["skipped"] == 1


def test_scan_skips_opted_out_user(client, db, monkeypatch):
    """用户已关闭关怀 → 不在候选集内，不发送也不计入扫描。"""
    login(client, "caring_user")
    monkeypatch.setattr(get_settings(), "wx_subscribe_template_id", "TPL_TEST")
    client.portal.call(_seed_streak("caring_user", quota=1, opt_out=True))

    stats = client.portal.call(caring.run_caring_scan)
    assert stats == {"scanned": 0, "sent": 0, "skipped": 0, "failed": 0}


def test_scan_requires_subscription_quota(client, db, monkeypatch):
    """无订阅授权配额（未授权）→ 不打扰，不发送。"""
    login(client, "caring_user")
    monkeypatch.setattr(get_settings(), "wx_subscribe_template_id", "TPL_TEST")
    client.portal.call(_seed_streak("caring_user", quota=0))

    stats = client.portal.call(caring.run_caring_scan)
    assert stats == {"scanned": 0, "sent": 0, "skipped": 0, "failed": 0}


# ---------- 用户侧接口 ----------

def test_caring_api_toggle_and_subscribe(client, db):
    """默认开启未订阅；可关闭；订阅授权后 subscribed=true。"""
    token = login(client)
    resp = client.get("/api/v1/users/me/caring", headers=auth(token))
    assert resp.json()["data"] == {"enabled": True, "subscribed": False}

    # 关闭关怀
    resp = client.put(
        "/api/v1/users/me/caring", json={"enabled": False}, headers=auth(token)
    )
    assert resp.json()["data"]["enabled"] is False

    # 订阅授权（同意）
    resp = client.post(
        "/api/v1/users/me/caring/subscribe", json={"granted": True}, headers=auth(token)
    )
    data = resp.json()["data"]
    assert data["subscribed"] is True and data["enabled"] is False

    # 重新开启
    resp = client.put(
        "/api/v1/users/me/caring", json={"enabled": True}, headers=auth(token)
    )
    assert resp.json()["data"] == {"enabled": True, "subscribed": True}


def test_caring_subscribe_rejected_no_quota(client, db):
    """用户拒绝订阅授权（granted=false）→ 不增加配额，subscribed 仍为 false。"""
    token = login(client)
    resp = client.post(
        "/api/v1/users/me/caring/subscribe", json={"granted": False}, headers=auth(token)
    )
    assert resp.json()["data"]["subscribed"] is False
