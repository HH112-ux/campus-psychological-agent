"""会话服务：创建、列表、详情、重命名、删除，强制 user_id 隔离。"""
from __future__ import annotations

from bson import ObjectId

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.exceptions import (
    CODE_NOT_FOUND,
    CODE_RESOURCE_FORBIDDEN,
    CODE_SESSION_CONCURRENCY_LIMIT,
    BizError,
)
from app.core.timeutil import now_cst, to_iso
from app.db.indexes import COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo
from app.db.oid import parse_oid


def serialize_session_brief(s: dict) -> dict:
    return {
        "session_id": str(s["_id"]),
        "title": s.get("title") or "新的对话",
        "rounds": s.get("rounds", 0),
        "status": s.get("status", "active"),
        "last_msg_at": to_iso(s["last_msg_at"]) if s.get("last_msg_at") else None,
    }


async def create_session(user_id: ObjectId, title: str | None) -> dict:
    settings = get_settings()
    active_count = await mongo.db[COLL_SESSIONS].count_documents(
        {"user_id": user_id, "status": "active"}
    )
    if active_count >= settings.session_concurrency_limit:
        raise BizError(
            CODE_SESSION_CONCURRENCY_LIMIT,
            "活跃会话已达上限，请先归档或删除一个旧会话",
            http_status=429,
        )
    now = now_cst()
    doc = {
        "user_id": user_id,
        "title": (title.strip() if title and title.strip() else None),
        "rounds": 0,
        "status": "active",
        "crisis_score": 0,          # 二级语境词累计分
        "crisis_high_shown": False,  # 本会话是否已展示过 high 级危机卡片
        "created_at": now,
        "last_msg_at": now,
    }
    result = await mongo.db[COLL_SESSIONS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def list_sessions(user_id: ObjectId, page: int, page_size: int) -> dict:
    query = {"user_id": user_id, "status": "active"}
    total = await mongo.db[COLL_SESSIONS].count_documents(query)
    cursor = (
        mongo.db[COLL_SESSIONS]
        .find(query)
        .sort("last_msg_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_session_brief(s) async for s in cursor]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


async def get_owned_session(session_id: str, user_id: ObjectId) -> dict:
    """取会话并校验归属；任何不符统一 404，不暴露存在性。"""
    s = await mongo.db[COLL_SESSIONS].find_one(
        {"_id": parse_oid(session_id), "status": "active"}
    )
    if s is None:
        raise BizError(CODE_NOT_FOUND, "会话不存在", http_status=404)
    if s.get("user_id") != user_id:
        raise BizError(CODE_RESOURCE_FORBIDDEN, "会话不存在", http_status=404)
    return s


async def get_detail(session_id: str, user_id: ObjectId) -> dict:
    s = await get_owned_session(session_id, user_id)
    settings = get_settings()
    # 最近 N 条按时间正序返回（先倒序取再反转）
    cursor = (
        mongo.db[COLL_MESSAGES]
        .find({"session_id": s["_id"]})
        .sort("created_at", -1)
        .limit(settings.session_messages_max_return)
    )
    msgs = [m async for m in cursor]
    msgs.reverse()
    return {
        "session_id": str(s["_id"]),
        "title": s.get("title") or "新的对话",
        "rounds": s.get("rounds", 0),
        "crisis_high_shown": s.get("crisis_high_shown", False),
        "messages": [_serialize_message(m) for m in msgs],
    }


def _serialize_message(m: dict) -> dict:
    item = {
        "message_id": str(m["_id"]),
        "role": m.get("role"),
        "content": decrypt(m.get("content")),  # P4：解密
        "created_at": to_iso(m.get("created_at")) if m.get("created_at") else None,
    }
    if m.get("role") == "assistant":
        item["emotion"] = m.get("emotion")  # P1 为 None，P3 填充
        item["feedback"] = m.get("feedback")
        item["degraded"] = m.get("degraded", False)
    return item


async def rename_session(session_id: str, user_id: ObjectId, title: str) -> dict:
    s = await get_owned_session(session_id, user_id)
    await mongo.db[COLL_SESSIONS].update_one(
        {"_id": s["_id"]}, {"$set": {"title": title.strip()}}
    )
    s["title"] = title.strip()
    return s


async def delete_session(session_id: str, user_id: ObjectId) -> None:
    s = await get_owned_session(session_id, user_id)
    await mongo.db[COLL_MESSAGES].delete_many({"session_id": s["_id"]})
    await mongo.db[COLL_SESSIONS].delete_one({"_id": s["_id"]})
