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
COLL_PRACTICE_LOGS = "practice_logs"  # 练习卡片完成记录（V4；仅记练习 id/类别/时长，不含对话或情绪原文）
COLL_MEMORIES = "memories"  # 长期记忆（V6；人物/事件/偏好/情绪诱因，正文加密，支持查看与删除）

_INDEX_SPECS: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    COLL_USERS: [([("openid", 1)], {"unique": True})],
    COLL_SESSIONS: [([("user_id", 1), ("last_msg_at", -1)], {})],
    COLL_MESSAGES: [([("session_id", 1), ("created_at", 1)], {})],
    COLL_EMOTION_RECORDS: [([("user_id", 1), ("created_at", -1)], {})],
    COLL_CHECKINS: [([("user_id", 1), ("date", 1)], {"unique": True})],
    COLL_RISK_EVENTS: [([("user_id", 1), ("created_at", -1)], {})],
    COLL_CARE_MESSAGES: [([("user_id", 1), ("created_at", -1)], {})],
    COLL_PRACTICE_LOGS: [([("user_id", 1), ("created_at", -1)], {})],
    # 查看/注入按最近更新倒序；content_hash 唯一索引用于抽取去重（同一事实不重复入库）
    COLL_MEMORIES: [
        ([("user_id", 1), ("updated_at", -1)], {}),
        ([("user_id", 1), ("content_hash", 1)], {"unique": True}),
    ],
}


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """为所有集合建立索引；已存在则跳过（幂等）。"""
    for coll_name, specs in _INDEX_SPECS.items():
        for keys, kwargs in specs:
            await db[coll_name].create_index(keys, **kwargs)
