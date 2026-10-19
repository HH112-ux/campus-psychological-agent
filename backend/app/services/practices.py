"""练习卡片服务（V4）。

把提示词里已有的「身体优先 / 呼吸练习」话术产品化：呼吸引导、正念引导、行为激活小任务，
以对话外可交互卡片呈现，完成情况落库（`practice_logs`）以便回看与统计。

设计与边界：
- 卡片为内置静态目录，**内容 [待专业审校]**（联动 M2 心理中心老师复核后调整文案）；
- 只做放松 / 觉察引导，不含医疗诊断、疗效承诺或「治疗」类表述；
- 完成记录仅落 `practice_id / 类别 / 时长`，不含对话或情绪原文（隐私基线）。
"""
from __future__ import annotations

from bson import ObjectId

from app.core.timeutil import date_str, now_cst
from app.db.indexes import COLL_PRACTICE_LOGS
from app.db.mongo import mongo

# 内置练习卡片目录（`reviewed=false` 表示尚未经专业审校）
CATALOG: list[dict] = [
    {
        "id": "breath_478",
        "category": "breathing",
        "title": "4-7-8 呼吸",
        "subtitle": "睡前放松，帮身体慢慢慢下来",
        "duration_seconds": 120,
        "pattern": {"inhale": 4, "hold": 7, "exhale": 8},
        "steps": [
            "找个舒服的姿势坐好或躺下",
            "用鼻子吸气 4 秒",
            "屏住呼吸 7 秒",
            "用嘴缓缓呼气 8 秒，再循环",
        ],
        "reviewed": False,
    },
    {
        "id": "breath_box",
        "category": "breathing",
        "title": "箱式呼吸",
        "subtitle": "找回节奏，让注意力落回来",
        "duration_seconds": 120,
        "pattern": {"inhale": 4, "hold": 4, "exhale": 4, "rest": 4},
        "steps": ["吸气 4 秒", "屏息 4 秒", "呼气 4 秒", "停留 4 秒，再循环"],
        "reviewed": False,
    },
    {
        "id": "mindful_3min",
        "category": "mindfulness",
        "title": "三分钟呼吸空间",
        "subtitle": "忙乱的时候，给自己三分钟",
        "duration_seconds": 180,
        "steps": [
            "第 1 分钟：觉察此刻的想法和感受，不评判好坏",
            "第 2 分钟：把注意力轻轻放到呼吸上",
            "第 3 分钟：把觉察扩展到全身和周围",
        ],
        "reviewed": False,
    },
    {
        "id": "activate_micro",
        "category": "activation",
        "title": "微小行动",
        "subtitle": "没力气的时候，从一件小事开始",
        "duration_seconds": 60,
        "tasks": ["起身接一杯水", "走到窗边看看天色", "给一位信任的人发一句话"],
        "reviewed": False,
    },
]

_BY_ID = {card["id"]: card for card in CATALOG}


async def list_practices(user_id: ObjectId) -> dict:
    """练习卡片目录 + 今日已完成标记（本地统计，便于回看）。"""
    if mongo.db is None:
        return {"practices": CATALOG, "completed_today": []}
    cursor = mongo.db[COLL_PRACTICE_LOGS].find(
        {"user_id": user_id, "date": date_str()}, {"practice_id": 1}
    )
    done = {doc["practice_id"] async for doc in cursor}
    practices = [{**card, "completed_today": card["id"] in done} for card in CATALOG]
    return {"practices": practices, "completed_today": sorted(done)}


async def complete_practice(
    user_id: ObjectId, practice_id: str, duration_seconds: int | None
) -> dict | None:
    """记录一次练习完成；未知练习返回 None（路由侧转 2001）。同日可多次。"""
    card = _BY_ID.get(practice_id)
    if card is None:
        return None
    await mongo.db[COLL_PRACTICE_LOGS].insert_one(
        {
            "user_id": user_id,
            "practice_id": practice_id,
            "category": card["category"],
            "duration_seconds": (
                duration_seconds if duration_seconds is not None else card["duration_seconds"]
            ),
            "date": date_str(),
            "created_at": now_cst(),
        }
    )
    times_today = await mongo.db[COLL_PRACTICE_LOGS].count_documents(
        {"user_id": user_id, "practice_id": practice_id, "date": date_str()}
    )
    return {"practice_id": practice_id, "completed": True, "times_today": times_today}
