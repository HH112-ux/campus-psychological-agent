"""会话窗口记忆：取近 N 轮（默认 20 轮，约 40 条）历史，按时间正序组装为多轮 messages。

P1：窗口截断（超出直接不取）。超窗历史的摘要压缩（≤200 字注入系统提示词头部）
为低频链路，P1 暂不启用，后续接入时不影响本函数对外形态。
会话切换不共享记忆（按 session_id 隔离）。
"""
from __future__ import annotations

from bson import ObjectId

from app.config import get_settings
from app.db.indexes import COLL_MESSAGES
from app.db.mongo import mongo


async def load_window(session_id: ObjectId, rounds: int | None = None) -> list[dict]:
    """返回最近 rounds 轮（user/assistant 各一条）的多轮消息，正序，供模型上下文使用。"""
    settings = get_settings()
    rounds = rounds or settings.memory_window_rounds
    limit = rounds * 2
    cursor = (
        mongo.db[COLL_MESSAGES]
        .find({"session_id": session_id, "role": {"$in": ["user", "assistant"]}})
        .sort("created_at", -1)
        .limit(limit)
    )
    msgs = [m async for m in cursor]
    msgs.reverse()
    return [{"role": m["role"], "content": m["content"]} for m in msgs]
