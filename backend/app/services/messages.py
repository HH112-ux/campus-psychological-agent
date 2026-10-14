"""消息域服务：消息级持久化/业务规则封装。

chat.py 负责对话编排（prepare_turn / reply_nonstream / stream_events），
这里封装消息级 CRUD 和 feedback 写入，避免路由层直接操作 mongo。
"""
from __future__ import annotations

from bson import ObjectId

from app.core.exceptions import (
    CODE_NOT_FOUND,
    CODE_RESOURCE_FORBIDDEN,
    BizError,
)
from app.db.indexes import COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo


async def record_feedback(
    message_id: ObjectId,
    user_id: ObjectId,
    rating: str,
    reason: str | None = None,
) -> None:
    """为 assistant 消息记录点赞/点踩。

    校验：消息必须是 assistant 角色、归属当前用户。校验失败抛 BizError。
    业务规则（如"30 天内可反馈"）可在此扩展，路由层无感。
    """
    msg = await mongo.db[COLL_MESSAGES].find_one(
        {"_id": message_id, "role": "assistant"}
    )
    if msg is None:
        raise BizError(CODE_NOT_FOUND, "回复不存在", http_status=404)

    session = await mongo.db[COLL_SESSIONS].find_one({"_id": msg.get("session_id")})
    if session is None or session.get("user_id") != user_id:
        raise BizError(CODE_RESOURCE_FORBIDDEN, "回复不存在", http_status=404)

    await mongo.db[COLL_MESSAGES].update_one(
        {"_id": msg["_id"]},
        {"$set": {"feedback": {"rating": rating, "reason": reason}}},
    )
