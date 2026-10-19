"""P3 情绪识别与日志测试：打卡、streak、情绪分析落库、时间线、趋势、隔离。

用 monkeypatch 替换 ZhipuProvider：轻量档（model_light）返回情绪 JSON，
主对话档（model_chat）返回共情文本，避免真实调用大模型。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pymongo
import pytest
from bson import ObjectId
from helpers import auth, create_session, login

from app.config import get_settings
from app.core.timeutil import CST, date_str, now_cst
from app.db.indexes import COLL_CHECKINS, COLL_EMOTION_RECORDS, COLL_USERS
from app.services import chat, emotion

EMOTION_JSON = (
    '{"emotion":"anxious","intensity":7,"evidence":"越学越慌，睡不着",'
    '"risk_level":"none","strategy_hint":"body_first"}'
)


def make_fake_llm(emotion_json: str = EMOTION_JSON, capture: list | None = None):
    """按模型档位分流：轻量档出情绪 JSON，主对话档出共情文本。"""

    async def fake_generate(self, messages, temperature=0.7, max_tokens=1024):
        if capture is not None:
            capture.append(messages)
        if self.model == get_settings().model_light:
            return emotion_json
        return "我在听，慢慢来，先做一个深呼吸。"

    async def fake_stream(self, messages, temperature=0.7, max_tokens=1024):
        for piece in ["我在听，", "慢慢来。"]:
            yield piece

    return fake_generate, fake_stream


@pytest.fixture()
def fake_llm(monkeypatch):
    gen, stream = make_fake_llm()
    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(chat.ZhipuProvider, "stream", stream)


def _send(client, token, sid, content, stream=False):
    return client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": content, "stream": stream},
        headers=auth(token),
    )


# ---------- 情绪 JSON 解析 ----------
def test_parse_emotion_json_valid_and_aliases():
    a = emotion.parse_emotion_json(EMOTION_JSON)
    assert a is not None
    assert a.emotion == "anxious" and a.intensity == 7
    assert a.evidence == "越学越慌，睡不着" and a.strategy_hint == "body_first"

    # markdown 围栏 + 中文情绪别名 + evidence 去空白
    raw = (
        '```json\n{"emotion":"焦虑","intensity":"8","evidence":"  有点慌  ",'
        '"risk_level":"中","strategy_hint":"body_first"}\n```'
    )
    a2 = emotion.parse_emotion_json(raw)
    assert a2 is not None
    assert a2.emotion == "anxious" and a2.intensity == 8
    assert a2.evidence == "有点慌" and a2.risk_level == "mid"

    # evidence 超 50 字截断
    raw3 = '{"emotion":"ok","intensity":3,"evidence":"' + "很" * 80 + '","risk_level":"none"}'
    a3 = emotion.parse_emotion_json(raw3)
    assert a3 is not None and len(a3.evidence) == 50


def test_parse_emotion_json_invalid_returns_none():
    assert emotion.parse_emotion_json("不是 JSON") is None
    assert emotion.parse_emotion_json('{"emotion":"外星情绪","intensity":3}') is None
    assert emotion.parse_emotion_json('{"emotion":"ok","intensity":99}') is None
    assert emotion.parse_emotion_json('{"emotion":"ok","intensity":"abc"}') is None
    assert emotion.parse_emotion_json("") is None


def test_parse_emotion_json_pipe_joined_takes_first_valid():
    """回归：模型把提示词枚举语法抄进值（"anxious|depressed"），取首个合法项，不得整体判失败。"""
    raw = (
        '```json {"emotion": "anxious|depressed", "intensity": 7, '
        '"evidence": "复习压力好大，睡不着", "risk_level": "high", '
        '"strategy_hint": "grounding|body_first"} ```'
    )
    a = emotion.parse_emotion_json(raw)
    assert a is not None
    assert a.emotion == "anxious"  # 管道分隔取首个合法项
    assert a.strategy_hint == "grounding"

    # 中文别名 + 管道混合
    a2 = emotion.parse_emotion_json('{"emotion":"低落|焦虑","intensity":6}')
    assert a2 is not None and a2.emotion == "depressed"

    # 全部非法仍判失败
    assert emotion.parse_emotion_json('{"emotion":"x|y|z","intensity":3}') is None


# ---------- 每日打卡 ----------
def test_checkin_create_upsert_and_today(client, db):
    token = login(client)
    r = client.post(
        "/api/v1/emotion/checkins",
        json={"mood": "anxious", "note": "明天出分，有点坐不住"},
        headers=auth(token),
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["mood"] == "anxious" and d["intensity"] == 7
    assert d["date"] == date_str()
    assert d["note"] == "明天出分，有点坐不住"
    assert d["updated"] is False
    assert d["streak"] == 1

    # 重复提交视为修改（updated=true），强度按新 mood 映射
    r2 = client.post(
        "/api/v1/emotion/checkins", json={"mood": "ok"}, headers=auth(token)
    )
    d2 = r2.json()["data"]
    assert d2["updated"] is True
    assert d2["mood"] == "ok" and d2["intensity"] == 4

    today = client.get("/api/v1/emotion/checkins/today", headers=auth(token))
    assert today.json()["data"]["mood"] == "ok"


def test_checkin_streak_counts_consecutive_days(client, db, monkeypatch):
    """通过替换 checkins 模块的日期函数模拟跨天打卡，验证连续天数统计。"""
    from app.services import checkins as checkins_svc

    base = datetime(2026, 10, 13, 12, 0, tzinfo=CST)
    cur = {"dt": base}
    monkeypatch.setattr(checkins_svc, "date_str", lambda: cur["dt"].strftime("%Y-%m-%d"))
    monkeypatch.setattr(checkins_svc, "now_cst", lambda: cur["dt"])

    token = login(client)
    headers = auth(token)

    # 10-11、10-12、10-13 连续打卡 → streak=3
    for offset in (2, 1, 0):
        cur["dt"] = base - timedelta(days=offset)
        client.post("/api/v1/emotion/checkins", json={"mood": "calm"}, headers=headers)
    me = client.get("/api/v1/users/me", headers=headers).json()["data"]
    assert me["checkin_streak"] == 3

    # 今天未打卡、昨天开始连续 → streak 从昨天起算 = 2（不打断，用新用户避免今日打卡干扰）
    token2 = login(client, mock_openid="streak_b")
    headers2 = auth(token2)
    cur["dt"] = base - timedelta(days=1)
    client.post("/api/v1/emotion/checkins", json={"mood": "ok"}, headers=headers2)
    cur["dt"] = base - timedelta(days=2)
    client.post("/api/v1/emotion/checkins", json={"mood": "low"}, headers=headers2)
    cur["dt"] = base  # 今天：无打卡
    me2 = client.get("/api/v1/users/me", headers=headers2).json()["data"]
    assert me2["checkin_streak"] == 2


def test_checkin_mood_validation(client, db):
    token = login(client)
    r = client.post(
        "/api/v1/emotion/checkins", json={"mood": "happy"}, headers=auth(token)
    )
    assert r.status_code == 422
    r2 = client.post(
        "/api/v1/emotion/checkins",
        json={"mood": "calm", "note": "x" * 201},
        headers=auth(token),
    )
    assert r2.status_code == 422


# ---------- 情绪分析落库 ----------
def test_emotion_record_written_after_message(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    d = _send(client, token, sid, "最近有点焦虑，越学越慌睡不着").json()["data"]
    assert d["emotion"]["type"] == "anxious"
    assert d["emotion"]["intensity"] == 7
    assert d["emotion"]["evidence"] == "越学越慌，睡不着"

    # emotion_records 落库（时间线可读到，仅结构化结果）
    records = client.get("/api/v1/emotion/records", headers=auth(token)).json()["data"]
    assert records["total"] == 1
    item = records["items"][0]
    assert item["source"] == "message" and item["emotion"] == "anxious"
    assert item["evidence"] == "越学越慌，睡不着"

    # assistant 消息 emotion 回填（会话详情可抽查一致）
    detail = client.get(f"/api/v1/sessions/{sid}", headers=auth(token)).json()["data"]
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"][0]
    assert assistant["emotion"]["type"] == "anxious"


def test_emotion_event_before_done_in_stream(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    r = _send(client, token, sid, "最近有点焦虑", stream=True)
    body = r.text
    assert "event: emotion" in body
    assert "event: done" in body
    assert body.index("event: emotion") < body.index("event: done")
    assert '"type": "anxious"' in body


def test_emotion_analysis_failure_skips_record(client, db, monkeypatch):
    gen, stream = make_fake_llm(emotion_json="这不是一个JSON")
    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(chat.ZhipuProvider, "stream", stream)

    token = login(client)
    sid = create_session(client, token)
    d = _send(client, token, sid, "最近有点焦虑").json()["data"]
    assert d["emotion"] is None  # 分析失败：不写库、不阻塞回复
    records = client.get("/api/v1/emotion/records", headers=auth(token)).json()["data"]
    assert records["total"] == 0


def test_strategy_layer_injected_from_latest_emotion(client, db, monkeypatch):
    captured: list = []
    gen, stream = make_fake_llm(capture=captured)
    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(chat.ZhipuProvider, "stream", stream)

    token = login(client)
    sid = create_session(client, token)
    _send(client, token, sid, "最近有点焦虑")
    _send(client, token, sid, "还是睡不着")

    # 第二轮的主对话系统提示词应注入上一轮情绪策略（F3 策略层）
    chat_calls = [
        msgs
        for msgs in captured
        if msgs and msgs[0]["content"].startswith("你是「小屿」")
    ]
    sys_prompt = chat_calls[-1][0]["content"]
    assert "当前轮情绪：anxious" in sys_prompt
    assert "身体优先" in sys_prompt  # anxious 7-10 → body_first 倾向


# ---------- 情绪记录时间线 ----------
def test_records_timeline_merges_sources(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    _send(client, token, sid, "最近有点焦虑，越学越慌睡不着")
    client.post(
        "/api/v1/emotion/checkins", json={"mood": "calm"}, headers=auth(token)
    )

    r = client.get("/api/v1/emotion/records", headers=auth(token))
    d = r.json()["data"]
    assert d["total"] == 2
    sources = {it["source"] for it in d["items"]}
    assert sources == {"message", "checkin"}
    # 按时间倒序
    times = [it["created_at"] for it in d["items"]]
    assert times == sorted(times, reverse=True)
    msg_item = next(it for it in d["items"] if it["source"] == "message")
    assert msg_item["evidence"] == "越学越慌，睡不着"
    assert msg_item["session_title"] and msg_item["session_title"].startswith("最近有点焦虑")
    assert msg_item["session_id"] == sid  # 供"定位到来源对话"跳转
    checkin_item = next(it for it in d["items"] if it["source"] == "checkin")
    assert checkin_item["evidence"] is None and checkin_item["session_title"] is None

    # 按情绪筛选
    r2 = client.get(
        "/api/v1/emotion/records?emotion=anxious", headers=auth(token)
    ).json()["data"]
    assert r2["total"] == 1 and r2["items"][0]["source"] == "message"


# ---------- 情绪趋势 ----------
def test_trends_aggregation(client, db, fake_llm):
    token = login(client)
    sid = create_session(client, token)
    _send(client, token, sid, "越学越慌睡不着")  # 对话 anxious 7
    client.post(
        "/api/v1/emotion/checkins", json={"mood": "anxious"}, headers=auth(token)
    )  # 打卡 anxious 7
    client.post(
        "/api/v1/emotion/checkins", json={"mood": "ok"}, headers=auth(token)
    )  # 覆盖今日为 ok 4

    d = client.get("/api/v1/emotion/trends?days=7", headers=auth(token)).json()["data"]
    assert d["window"] == 7 and d["granularity"] == "day"
    # 对话 anxious 7 + 打卡 ok 4 → 均值 (7+4)/2 = 5.5
    assert d["avg_intensity"] == 5.5
    assert d["dominant_emotion"]["type"] == "anxious"
    assert d["dominant_emotion"]["ratio"] == 0.5
    today_point = next(p for p in d["points"] if p["date"] == date_str())
    assert today_point["count"] == 2 and today_point["avg_intensity"] == 5.5
    assert d["prev_avg_intensity"] is None  # 上一窗口无数据


def test_trends_empty(client, db):
    token = login(client)
    d = client.get("/api/v1/emotion/trends", headers=auth(token)).json()["data"]
    assert d["avg_intensity"] is None
    assert d["prev_avg_intensity"] is None
    assert d["dominant_emotion"] is None
    assert len(d["points"]) == 7  # 7 天窗口，无记录置 null 不补 0


def test_trends_checkin_only_dominant(client, db):
    """回归：仅打卡来源数据时，趋势主导情绪按归一化 emotion 聚合，不得崩溃。"""
    token = login(client)
    client.post(
        "/api/v1/emotion/checkins", json={"mood": "low"}, headers=auth(token)
    )  # low → depressed 6
    d = client.get("/api/v1/emotion/trends?days=7", headers=auth(token)).json()["data"]
    assert d["avg_intensity"] == 6.0
    assert d["dominant_emotion"]["type"] == "depressed"
    assert d["dominant_emotion"]["ratio"] == 1.0
    today_point = next(p for p in d["points"] if p["date"] == date_str())
    assert today_point["count"] == 1


# ---------- 记忆型问候 ----------
def test_users_me_streak_and_memory_greeting(client, db, fake_llm):
    token = login(client)
    # 无记录：无问候
    me0 = client.get("/api/v1/users/me", headers=auth(token)).json()["data"]
    assert me0["memory_greeting"] is None and me0["checkin_streak"] == 0

    _send(client, token, create_session(client, token), "越学越慌睡不着")
    me = client.get("/api/v1/users/me", headers=auth(token)).json()["data"]
    assert me["checkin_streak"] == 0  # 对话情绪不算打卡连续天数
    assert me["memory_greeting"] and "今天感觉好些了吗" in me["memory_greeting"]
    assert "越学越慌" in me["memory_greeting"]


# ---------- 用户隔离 ----------
def test_emotion_data_user_isolation(client, db, fake_llm):
    token_a = login(client, mock_openid="iso_a")
    token_b = login(client, mock_openid="iso_b")
    _send(client, token_a, create_session(client, token_a), "越学越慌睡不着")
    client.post(
        "/api/v1/emotion/checkins", json={"mood": "anxious"}, headers=auth(token_a)
    )

    records_b = client.get("/api/v1/emotion/records", headers=auth(token_b)).json()[
        "data"
    ]
    assert records_b["total"] == 0
    trends_b = client.get("/api/v1/emotion/trends", headers=auth(token_b)).json()[
        "data"
    ]
    assert trends_b["avg_intensity"] is None
    assert (
        client.get("/api/v1/emotion/checkins/today", headers=auth(token_b)).json()[
            "data"
        ]
        is None
    )
    me_b = client.get("/api/v1/users/me", headers=auth(token_b)).json()["data"]
    assert me_b["memory_greeting"] is None


# ---------- V2 周报洞察 ----------
def _sync_db():
    client = pymongo.MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    return client, client[os.environ.get("MONGODB_DB", "xinyu_test")]


def _uid_by_openid(openid="mock_test_user"):
    client, sdb = _sync_db()
    doc = sdb[COLL_USERS].find_one({"openid": openid})
    client.close()
    return doc["_id"]


def _seed_emotion(sdb, uid, emo, intensity, ts):
    sdb[COLL_EMOTION_RECORDS].insert_one(
        {
            "_id": ObjectId(),
            "user_id": uid,
            "source": "message",
            "ref_id": ObjectId(),
            "emotion": emo,
            "intensity": intensity,
            "evidence": None,
            "risk_level": "none",
            "strategy_hint": "naming",
            "created_at": ts,
        }
    )


def _seed_checkin(sdb, uid, mood, intensity, ts):
    sdb[COLL_CHECKINS].insert_one(
        {
            "_id": ObjectId(),
            "user_id": uid,
            "date": ts.strftime("%Y-%m-%d"),
            "mood": mood,
            "intensity": intensity,
            "note": None,
            "created_at": ts,
        }
    )


def _at(now, days_ago, hour, minute=0):
    """业务时区下「N 天前 HH:MM」的时间点（用于构造确定性的时段样本）。"""
    return (now - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def test_weekly_insight_empty(client, db):
    token = login(client)
    d = client.get("/api/v1/emotion/weekly-insight", headers=auth(token)).json()["data"]
    assert d["has_data"] is False
    assert d["record_count"] == 0 and d["record_days"] == 0
    assert d["dominant_emotion"] is None and d["peak_period"] is None
    assert d["intensity_trend"] == "none" and d["period_counts"] == {}
    assert d["window_days"] == 7 and d["start_date"] and d["end_date"]
    assert len(d["highlights"]) == 1 and "还没有情绪记录" in d["highlights"][0]


def test_weekly_insight_descriptive_peak_and_trend(client, db):
    """描述性小结：主导情绪 + 时段 + 与上周对比 + 打卡，且不含归因断言。"""
    token = login(client, mock_openid="wk_insight")
    uid = _uid_by_openid("wk_insight")
    sdb_client, sdb = _sync_db()
    now = now_cst()

    # 本周：3 条焦虑（均出现在晚上/傍晚）+ 1 条平静（早上）
    _seed_emotion(sdb, uid, "anxious", 8, _at(now, 1, 20))
    _seed_emotion(sdb, uid, "anxious", 7, _at(now, 1, 19, 30))
    _seed_emotion(sdb, uid, "anxious", 6, _at(now, 2, 21))
    _seed_emotion(sdb, uid, "calm", 3, _at(now, 3, 9))
    # 上一窗口：更高强度（用于趋势对比：本周应「略有下降」）
    _seed_emotion(sdb, uid, "anxious", 9, _at(now, 9, 20))
    _seed_emotion(sdb, uid, "anxious", 9, _at(now, 10, 20))
    # 打卡 2 天
    _seed_checkin(sdb, uid, "ok", 4, _at(now, 1, 8))
    _seed_checkin(sdb, uid, "low", 6, _at(now, 2, 8))
    sdb_client.close()

    d = client.get("/api/v1/emotion/weekly-insight", headers=auth(token)).json()["data"]
    assert d["has_data"] is True
    assert d["record_count"] == 6 and d["checkin_days"] == 2
    assert d["dominant_emotion"]["type"] == "anxious"
    assert d["peak_period"] == "evening" and d["peak_period_label"] == "晚上"
    assert d["intensity_trend"] == "down"
    assert d["avg_intensity"] == 5.7 and d["prev_avg_intensity"] == 9.0

    joined = " ".join(d["highlights"])
    assert "本周以「焦虑」为主" in joined
    assert "「焦虑」多出现在晚上" in joined
    assert "略有下降" in joined
    assert "本周打卡 2 天" in joined
    # 红线：只做描述性结论，不得出现归因断言
    for bad in ("因为", "导致", "由于"):
        assert bad not in joined


def test_weekly_insight_night_not_misbucketed(client, db):
    """回归：凌晨 02:00（深夜）记录按业务时区归类。

    motor 读回为 naive UTC（02:00 CST = 前一日 18:00 UTC），不做时区归一会被错分到
    「下午」；本用例确保修正后归为「深夜」。
    """
    token = login(client, mock_openid="wk_night")
    uid = _uid_by_openid("wk_night")
    sdb_client, sdb = _sync_db()
    now = now_cst()
    night = _at(now, 2, 2)
    _seed_emotion(sdb, uid, "depressed", 6, night)
    _seed_emotion(sdb, uid, "depressed", 5, night + timedelta(minutes=10))
    sdb_client.close()

    d = client.get("/api/v1/emotion/weekly-insight", headers=auth(token)).json()["data"]
    assert d["dominant_emotion"]["type"] == "depressed"
    assert d["peak_period"] == "night" and d["peak_period_label"] == "深夜"
    assert "「低落」多出现在深夜" in " ".join(d["highlights"])


def test_weekly_insight_user_isolation(client, db):
    login(client, mock_openid="wk_a")
    token_b = login(client, mock_openid="wk_b")
    uid_a = _uid_by_openid("wk_a")
    sdb_client, sdb = _sync_db()
    _seed_emotion(sdb, uid_a, "anxious", 7, now_cst() - timedelta(hours=1))
    sdb_client.close()

    d = client.get("/api/v1/emotion/weekly-insight", headers=auth(token_b)).json()["data"]
    assert d["has_data"] is False and d["record_count"] == 0
