"""隐私同意与数据权利服务（P4）。

- 隐私同意：记录 consent_at + 政策版本号，未同意时小程序必须先弹窗；
- 数据导出：同步导出用户全部数据为 JSON（会话/消息/情绪记录/打卡/风险事件）；
- 数据删除：软删（标记 deleted_at + erase_at），30 天可登录撤销，期满物理删除。
  软删后各查询接口不再返回任何数据（已由 users.get_by_id 的 deleted_at 过滤保障）。
"""
from __future__ import annotations

import logging

from bson import ObjectId

from app.core.crypto import decrypt
from app.core.timeutil import now_cst, to_iso
from app.db.indexes import (
    COLL_CHECKINS,
    COLL_EMOTION_RECORDS,
    COLL_MESSAGES,
    COLL_RISK_EVENTS,
    COLL_SESSIONS,
    COLL_USERS,
)
from app.db.mongo import mongo
from app.db.oid import parse_oid

logger = logging.getLogger(__name__)

# 软删恢复期（天）
ERASE_RECOVER_DAYS = 30

# 当前隐私政策版本
PRIVACY_POLICY_VERSION = "1.0"


async def record_consent(user_id: ObjectId, policy_version: str | None = None) -> dict:
    """记录用户隐私同意。"""
    now = now_cst()
    await mongo.db[COLL_USERS].update_one(
        {"_id": user_id},
        {"$set": {
            "consent_at": now,
            "consent_policy_version": policy_version or PRIVACY_POLICY_VERSION,
            "updated_at": now,
        }},
    )
    return {"consented": True, "consent_at": to_iso(now)}


async def export_user_data(user_id: ObjectId) -> dict:
    """导出用户全部数据为 JSON（明文解密后的对话内容）。

    用于 PIPL 行权：用户有权获取自己的全部个人信息副本。
    """
    uid = parse_oid(str(user_id))

    # 用户基本信息
    user_doc = await mongo.db[COLL_USERS].find_one({"_id": uid})
    user_info = {}
    if user_doc:
        user_info = {
            "user_id": str(user_doc["_id"]),
            "nickname": user_doc.get("nickname"),
            "avatar": user_doc.get("avatar"),
            "consent_at": to_iso(user_doc.get("consent_at")) if user_doc.get("consent_at") else None,
            "created_at": to_iso(user_doc.get("created_at")) if user_doc.get("created_at") else None,
        }

    # 会话列表
    sessions = []
    session_ids = []
    async for s in mongo.db[COLL_SESSIONS].find({"user_id": uid}).sort("created_at", 1):
        sessions.append({
            "session_id": str(s["_id"]),
            "title": s.get("title", ""),
            "rounds": s.get("rounds", 0),
            "created_at": to_iso(s.get("created_at")) if s.get("created_at") else None,
            "last_msg_at": to_iso(s.get("last_msg_at")) if s.get("last_msg_at") else None,
        })
        session_ids.append(s["_id"])

    # 消息列表（解密 content，仅该用户的会话）
    messages = []
    if session_ids:
        async for m in mongo.db[COLL_MESSAGES].find(
            {"session_id": {"$in": session_ids}}
        ).sort("created_at", 1):
            messages.append({
                "message_id": str(m["_id"]),
                "session_id": str(m.get("session_id", "")),
                "role": m.get("role", ""),
                "content": decrypt(m.get("content")),
                "emotion": m.get("emotion"),
                "risk_level": m.get("risk_level", "none"),
                "feedback": m.get("feedback"),
                "degraded": m.get("degraded", False),
                "created_at": to_iso(m.get("created_at")) if m.get("created_at") else None,
            })

    # 情绪记录
    emotions = []
    async for e in mongo.db[COLL_EMOTION_RECORDS].find({"user_id": uid}).sort("created_at", 1):
        emotions.append({
            "emotion": e.get("emotion"),
            "intensity": e.get("intensity"),
            "evidence": e.get("evidence"),
            "risk_level": e.get("risk_level"),
            "strategy_hint": e.get("strategy_hint"),
            "created_at": to_iso(e.get("created_at")) if e.get("created_at") else None,
        })

    # 打卡记录
    checkins = []
    async for c in mongo.db[COLL_CHECKINS].find({"user_id": uid}).sort("date", 1):
        checkins.append({
            "date": c.get("date"),
            "mood": c.get("mood"),
            "note": c.get("note"),
            "created_at": to_iso(c.get("created_at")) if c.get("created_at") else None,
        })

    # 风险事件（仅命中词，不含对话原文）
    risk_events = []
    async for r in mongo.db[COLL_RISK_EVENTS].find({"user_id": uid}).sort("created_at", 1):
        risk_events.append({
            "level": r.get("level"),
            "trigger": r.get("trigger"),
            "matched": r.get("matched", []),
            "created_at": to_iso(r.get("created_at")) if r.get("created_at") else None,
        })

    return {
        "user": user_info,
        "sessions": sessions,
        "messages": messages,
        "emotion_records": emotions,
        "checkins": checkins,
        "risk_events": risk_events,
        "exported_at": to_iso(now_cst()),
    }


async def erase_user_data(user_id: ObjectId) -> dict:
    """软删用户全部数据：标记 deleted_at + erase_at，30 天后物理删除。

    立即生效：users.get_by_id 的 deleted_at 过滤使后续查询返回 None，
    各业务接口（/me、会话、消息等）从此刻起不再返回任何数据。
    """
    now = now_cst()
    from datetime import timedelta
    recover_deadline = now + timedelta(days=ERASE_RECOVER_DAYS)

    uid = parse_oid(str(user_id))

    # 1) 标记用户软删（各查询已通过 deleted_at != None 过滤）
    await mongo.db[COLL_USERS].update_one(
        {"_id": uid, "deleted_at": None},
        {"$set": {
            "deleted_at": now,
            "erase_at": recover_deadline,
            "current_refresh_jti": None,  # 使 refresh token 失效
            "updated_at": now,
        }},
    )

    # 2) 作废该用户所有会话（标记删除，查询侧按 user + deleted_at 过滤）
    await mongo.db[COLL_SESSIONS].update_many(
        {"user_id": uid},
        {"$set": {"deleted_at": now}},
    )

    logger.info("用户 %s 已软删，恢复截止 %s", uid, to_iso(recover_deadline))
    return {
        "erase_at": to_iso(now),
        "recover_deadline": to_iso(recover_deadline),
    }


async def recover_user(user_id: ObjectId) -> bool:
    """撤销软删（用户在 30 天内登录即可恢复）。"""
    uid = parse_oid(str(user_id))
    result = await mongo.db[COLL_USERS].update_one(
        {"_id": uid, "deleted_at": {"$ne": None}},
        {"$set": {"deleted_at": None, "erase_at": None, "updated_at": now_cst()}},
    )
    if result.modified_count:
        await mongo.db[COLL_SESSIONS].update_many(
            {"user_id": uid, "deleted_at": {"$ne": None}},
            {"$set": {"deleted_at": None}},
        )
        logger.info("用户 %s 撤销删除", uid)
        return True
    return False


async def purge_expired_data() -> int:
    """物理删除已过恢复期的用户数据（定时任务调用）。

    返回删除的用户数。
    """
    now = now_cst()
    cursor = mongo.db[COLL_USERS].find(
        {"deleted_at": {"$ne": None}, "erase_at": {"$lte": now}},
    )
    count = 0
    async for user in cursor:
        uid = user["_id"]
        # 先获取 session_ids（用于消息关联删除），再逐集合删除
        session_ids = [
            s["_id"] async for s in mongo.db[COLL_SESSIONS].find({"user_id": uid}, {"_id": 1})
        ]
        if session_ids:
            await mongo.db[COLL_MESSAGES].delete_many({"session_id": {"$in": session_ids}})
        await mongo.db[COLL_SESSIONS].delete_many({"user_id": uid})
        await mongo.db[COLL_EMOTION_RECORDS].delete_many({"user_id": uid})
        await mongo.db[COLL_CHECKINS].delete_many({"user_id": uid})
        await mongo.db[COLL_RISK_EVENTS].delete_many({"user_id": uid})
        await mongo.db[COLL_USERS].delete_one({"_id": uid})
        count += 1
        logger.info("物理删除用户 %s 全部数据", uid)
    return count
