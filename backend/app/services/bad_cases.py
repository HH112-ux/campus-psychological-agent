"""V1 反馈闭环：bad-case（点踩）收集与汇总。

把已收集的点赞/点踩做成复盘原料：导出点踩回复及触发它的用户消息（解密），
供双周复盘人工归类（模板见 docs/bad-case-review-template.md），形成
「收集 → 复盘 → 提示词/词库迭代 → E1 回归验证」的循环。

隐私红线：导出含解密对话内容，仅供运营复盘，文件严禁提交 Git；
复盘留档只记录归因与迭代项，不粘贴原文。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.crypto import decrypt
from app.core.timeutil import now_cst
from app.db.indexes import COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo


async def collect_bad_cases(since: datetime | None = None) -> list[dict]:
    """收集点踩的 assistant 消息，并配对触发它的上一条用户消息（均解密）。

    since 为 None 时全量；按时间正序返回，便于复盘按时间线过案例。
    """
    db = mongo.db
    if db is None:
        return []
    query: dict = {"role": "assistant", "feedback.rating": "dislike"}
    if since is not None:
        query["created_at"] = {"$gte": since}

    cases: list[dict] = []
    async for msg in db[COLL_MESSAGES].find(query).sort("created_at", 1):
        user_msg = await db[COLL_MESSAGES].find_one(
            {
                "session_id": msg["session_id"],
                "role": "user",
                "created_at": {"$lt": msg["created_at"]},
            },
            sort=[("created_at", -1)],
        )
        session = await db[COLL_SESSIONS].find_one(
            {"_id": msg["session_id"]}, {"title": 1}
        )
        feedback = msg.get("feedback") or {}
        created_at = msg.get("created_at")
        cases.append(
            {
                "message_id": str(msg["_id"]),
                "session_id": str(msg["session_id"]),
                "session_title": (session or {}).get("title"),
                "created_at": created_at.isoformat() if created_at else None,
                "reason": feedback.get("reason"),
                "user_message": decrypt(user_msg.get("content")) if user_msg else None,
                "assistant_reply": decrypt(msg.get("content")),
                "emotion": msg.get("emotion"),
                "degraded": bool(msg.get("degraded", False)),
            }
        )
    return cases


def summarize(cases: list[dict]) -> dict:
    """按点踩原因聚合计数（降序），供复盘开头写样本概览。"""
    by_reason: dict[str, int] = {}
    for case in cases:
        key = case.get("reason") or "unknown"
        by_reason[key] = by_reason.get(key, 0) + 1
    return {
        "total": len(cases),
        "by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
    }


def default_since(days: int) -> datetime:
    """近 N 天窗口起点（对齐双周复盘节奏，默认 14 天）。"""
    return now_cst() - timedelta(days=days)
