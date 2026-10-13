"""每日打卡服务（开发文档 F1 / API 文档第 7 节）。

- 每用户每日仅一条（user_id+date 唯一索引），重复提交视为修改（updated=true）；
- 日期以服务器时区（Asia/Shanghai）为准，避免客户端改时间刷连续天数；
- intensity 由 mood 按固定映射生成（calm=2 / ok=4 / low=6 / anxious=7 / irritable=6）；
- 连续记录天数（streak）从今天往回数，今天未打卡时从昨天开始连续计数（不打断）；
- 记忆型问候（F1/P3）：读取最近一条情绪记录，套用固定话术模板，不调用大模型。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId

from app.core.timeutil import date_str, now_cst, to_iso
from app.db.indexes import COLL_CHECKINS, COLL_EMOTION_RECORDS
from app.db.mongo import mongo

# F1 情绪档位 → 强度默认映射（专家判断，见开发文档 F1 规则约束）
MOOD_INTENSITY = {"calm": 2, "ok": 4, "low": 6, "anxious": 7, "irritable": 6}

# 记忆型问候模板：按情绪类别套固定话术（evidence 为空时用通用版）
_GREETING_TEMPLATES = {
    "anxious": ("上次你说“{evidence}”，今天感觉好些了吗？", "上次你有点焦虑，今天感觉好些了吗？"),
    "depressed": ("上次你提到“{evidence}”，今天想聊聊吗？", "上次你有些低落，今天想聊聊吗？"),
    "angry": ("上次你说“{evidence}”，现在气消了些吗？", "上次你有点烦躁，今天好些了吗？"),
    "calm": ("上次你状态平静，今天也记得照顾好自己呀", "上次你状态平静，今天也记得照顾好自己呀"),
    "ok": ("上次你状态不错，今天也记得照顾好自己呀", "上次你状态不错，今天也记得照顾好自己呀"),
    "other": ("上次你提到“{evidence}”，最近怎么样？", "最近怎么样？我一直在这里听你说。"),
}


def _serialize(doc: dict) -> dict:
    return {
        "checkin_id": str(doc["_id"]),
        "date": doc["date"],
        "mood": doc["mood"],
        "intensity": doc["intensity"],
        "note": doc.get("note"),
        "created_at": to_iso(doc.get("created_at")) if doc.get("created_at") else None,
    }


async def upsert_checkin(user_id: ObjectId, mood: str, note: str | None) -> dict:
    """写入/覆盖今日打卡，返回 API 文档约定的 data（含 updated 与 streak）。"""
    today = date_str()
    now = now_cst()
    result = await mongo.db[COLL_CHECKINS].update_one(
        {"user_id": user_id, "date": today},
        {
            "$set": {"mood": mood, "intensity": MOOD_INTENSITY[mood], "note": note},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    created_doc = await mongo.db[COLL_CHECKINS].find_one(
        {"user_id": user_id, "date": today}
    )
    data = _serialize(created_doc)
    data["updated"] = result.upserted_id is None
    data["streak"] = await compute_streak(user_id)
    return data


async def get_today(user_id: ObjectId) -> dict | None:
    """今日打卡；无记录返回 None（首页据此渲染打卡区或已打卡卡片）。"""
    doc = await mongo.db[COLL_CHECKINS].find_one(
        {"user_id": user_id, "date": date_str()}
    )
    return _serialize(doc) if doc else None


async def compute_streak(user_id: ObjectId) -> int:
    """连续打卡天数：从今天（或昨天）起连续往前数。"""
    if mongo.db is None:
        return 0
    docs = (
        mongo.db[COLL_CHECKINS]
        .find({"user_id": user_id}, {"date": 1})
        .sort("date", -1)
    )
    dates = {d["date"] async for d in docs}
    if not dates:
        return 0

    cursor = date_str()  # 今天
    if cursor not in dates:
        cursor = (now_cst() - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = 0
    while cursor in dates:
        streak += 1
        cursor = (datetime.strptime(cursor, "%Y-%m-%d") - timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
    return streak


async def latest_emotion(user_id: ObjectId) -> dict | None:
    """最近一条情绪记录（对话来源 + 打卡来源合并取最新），供记忆型问候。"""
    if mongo.db is None:
        return None
    emo = await mongo.db[COLL_EMOTION_RECORDS].find_one(
        {"user_id": user_id}, sort=[("created_at", -1)]
    )
    return emo if emo else None


def _greeting_from(emotion: str, intensity: int, evidence: str | None) -> str | None:
    template = _GREETING_TEMPLATES.get(emotion)
    if not template:
        return None
    if evidence:
        return template[0].format(evidence=evidence)
    return template[1]


async def memory_greeting(user_id: ObjectId) -> str | None:
    """基于最近一条情绪记录生成固定话术问候；无记录返回 None。"""
    emo = await latest_emotion(user_id)
    if emo is None:
        return None
    return _greeting_from(
        emo.get("emotion", "other"), emo.get("intensity", 3), emo.get("evidence")
    )
