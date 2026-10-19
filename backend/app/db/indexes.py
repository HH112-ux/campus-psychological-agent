"""数据库集合与索引初始化（对齐《开发文档》数据模型）。"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

# 集合名常量（后续业务模块统一引用，避免散落字符串）
COLL_USERS = "users"
COLL_SESSIONS = "sessions"
COLL_MESSAGES = "messages"
COLL_EMOTION_RECORDS = "emotion_records"
COLL_CHECKINS = "checkins"
COLL_RISK_EVENTS = "risk_events"
COLL_CRISIS_LEXICON = "crisis_lexicon"  # 危机词库（P1 起使用，配置热更新）
COLL_CRISIS_RESOURCES = "crisis_resources"  # 求助资源（运营配置，P1 起使用）
COLL_CARE_MESSAGES = "care_messages"  # 主动关怀发送留档（V3，周频控依据；仅记类型/状态，不含内容）

_INDEX_SPECS: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    COLL_USERS: [([("openid", 1)], {"unique": True})],
    COLL_SESSIONS: [([("user_id", 1), ("last_msg_at", -1)], {})],
    COLL_MESSAGES: [([("session_id", 1), ("created_at", 1)], {})],
    COLL_EMOTION_RECORDS: [([("user_id", 1), ("created_at", -1)], {})],
    COLL_CHECKINS: [([("user_id", 1), ("date", 1)], {"unique": True})],
    COLL_RISK_EVENTS: [([("user_id", 1), ("created_at", -1)], {})],
    COLL_CARE_MESSAGES: [([("user_id", 1), ("created_at", -1)], {})],
}


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """为所有集合建立索引；已存在则跳过（幂等）。"""
    for coll_name, specs in _INDEX_SPECS.items():
        for keys, kwargs in specs:
            await db[coll_name].create_index(keys, **kwargs)
