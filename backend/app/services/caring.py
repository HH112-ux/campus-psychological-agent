"""主动关怀服务（V3）。

机制：基于情绪日志（连续 N 天低落 / 打卡中断），次日通过微信订阅消息温和问候、
引导打卡；用户可随时关闭。

红线与约束（roadmap §V3）：
- **订阅授权**：仅对用户已授权（`care_subscribe_count > 0`，一次性订阅每次授权 +1）
  且未关闭关怀的用户发送；发一条扣减一次配额；
- **频控**：同一用户每周最多 `caring_max_per_week` 条（依据 care_messages 留档计数）；
- **文案克制**：问候语为温和邀请，不做说教/命令（可复用 bad-case 的 `preachy` 负面样本）；
- **隐私基线**：留档只记触发类型与发送状态，不落情绪证据或对话原文；
- **fail-safe**：未配置订阅模板 ID / 开关关闭时安全跳过，不影响主链路与调度。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from bson import ObjectId

from app.config import get_settings
from app.core.timeutil import date_str, now_cst
from app.db.indexes import COLL_CARE_MESSAGES, COLL_CHECKINS, COLL_USERS
from app.db.mongo import mongo
from app.services import wechat

logger = logging.getLogger(__name__)

# 负面情绪档位（查档 low/anxious/irritable → 触发 low_streak 判定）
_NEGATIVE_MOODS = {"low", "anxious", "irritable"}

# 触发类型 → 温和问候语（thing 类型字段限 20 字符，避免说教/命令句式）
_GREETINGS = {
    "low_streak": "这几天辛苦了，我一直在这里听你说",
    "checkin_gap": "有阵子没见啦，最近过得怎么样？",
}

# 微信 thing 类型 value 长度上限（超出会以 47003 发送失败）
_MAX_TEXT_LEN = 20
# 关怀去重/频控回看窗口
_WEEK_DAYS = 7


def _truncate(text: str) -> str:
    return text[:_MAX_TEXT_LEN]


def _is_prev_day(later: str, earlier: str) -> bool:
    """later 是否为 earlier 的次日（按 yyyy-mm-dd 解析）。"""
    try:
        d1 = datetime.strptime(later, "%Y-%m-%d")
        d2 = datetime.strptime(earlier, "%Y-%m-%d")
    except ValueError:
        return False
    return (d1 - d2).days == 1


def _evaluate_trigger(docs: list[dict], today: str) -> str | None:
    """依据打卡记录（按 date 倒序）判定触发类型：low_streak / checkin_gap / None。

    low_streak：自最近一次打卡往前，连续且每日均为负面档位，长度 ≥ 阈值；
    checkin_gap：有历史打卡但最近一次打卡距 today ≥ 中断阈值天（近期未打卡）。
    """
    settings = get_settings()
    if not docs:
        return None

    # 连续低落：从最近打卡日起，向前数连续日期段
    run = [docs[0]]
    for prev, cur in zip(docs, docs[1:]):
        if _is_prev_day(prev["date"], cur["date"]):
            run.append(cur)
        else:
            break
    if len(run) >= settings.caring_low_streak_days and all(
        d.get("mood") in _NEGATIVE_MOODS for d in run
    ):
        return "low_streak"

    # 打卡中断：最近打卡日已距今天 ≥ 阈值天
    last_date = docs[0]["date"]
    gap = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last_date, "%Y-%m-%d")).days
    if gap >= settings.caring_checkin_gap_days:
        return "checkin_gap"
    return None


async def _recent_checkins(user_id: ObjectId, days: int = 30) -> list[dict]:
    """近 N 天打卡记录（date 倒序），仅取 date/mood 两个字段。"""
    since = (now_cst() - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor = (
        mongo.db[COLL_CHECKINS]
        .find({"user_id": user_id, "date": {"$gte": since}}, {"date": 1, "mood": 1})
        .sort("date", -1)
    )
    return [doc async for doc in cursor]


async def _sent_count_last_week(user_id: ObjectId) -> int:
    """近 7 天成功发送条数（仅计 status=sent，作为频控依据）。"""
    since = now_cst() - timedelta(days=_WEEK_DAYS)
    return await mongo.db[COLL_CARE_MESSAGES].count_documents(
        {"user_id": user_id, "status": "sent", "created_at": {"$gte": since}}
    )


async def _record(user_id: ObjectId, kind: str, status: str, errcode: int | None = None) -> None:
    """留档一条发送记录（不落问候原文/情绪证据，符合隐私基线）。"""
    doc = {"user_id": user_id, "kind": kind, "status": status, "created_at": now_cst()}
    if errcode is not None:
        doc["errcode"] = errcode
    await mongo.db[COLL_CARE_MESSAGES].insert_one(doc)


async def _send_to_user(user: dict) -> str:
    """向单个用户尝试发送关怀；返回 sent / skipped / failed。"""
    settings = get_settings()
    uid = user["_id"]

    kind = _evaluate_trigger(await _recent_checkins(uid), date_str())
    if kind is None:
        return "skipped"

    if await _sent_count_last_week(uid) >= settings.caring_max_per_week:
        return "skipped"

    data = {settings.wx_subscribe_field_key: {"value": _truncate(_GREETINGS[kind])}}
    try:
        resp = await wechat.send_subscribe_message(
            user["openid"], settings.wx_subscribe_template_id, data
        )
    except Exception:
        logger.exception("V3 主动关怀：订阅消息发送异常 user=%s kind=%s", uid, kind)
        await _record(uid, kind, "failed")
        return "failed"

    if resp.get("errcode") != 0:
        logger.warning(
            "V3 主动关怀：订阅消息发送失败 user=%s kind=%s errcode=%s",
            uid, kind, resp.get("errcode"),
        )
        await _record(uid, kind, "failed", resp.get("errcode"))
        return "failed"

    # 成功：扣减一次性订阅配额并留档
    await mongo.db[COLL_USERS].update_one(
        {"_id": uid}, {"$inc": {"care_subscribe_count": -1}}
    )
    await _record(uid, kind, "sent")
    return "sent"


# ---------- 用户侧开关与订阅授权（API 文档第 8 节） ----------


async def get_caring_state(user_id: ObjectId) -> dict:
    """读取用户关怀状态：enabled=未关闭关怀；subscribed=仍有订阅配额。"""
    user = await mongo.db[COLL_USERS].find_one(
        {"_id": user_id}, {"caring_opt_out": 1, "care_subscribe_count": 1}
    ) or {}
    return {
        "enabled": not user.get("caring_opt_out", False),
        "subscribed": user.get("care_subscribe_count", 0) > 0,
    }


async def set_caring_enabled(user_id: ObjectId, enabled: bool) -> dict:
    """开启/关闭主动关怀（用户可随时关闭）。"""
    await mongo.db[COLL_USERS].update_one(
        {"_id": user_id},
        {"$set": {"caring_opt_out": not enabled, "updated_at": now_cst()}},
    )
    return await get_caring_state(user_id)


async def record_subscription(user_id: ObjectId, granted: bool) -> dict:
    """回填订阅授权结果：同意则订阅配额 +1（微信一次性订阅，每次授权可发一条）。"""
    if granted:
        await mongo.db[COLL_USERS].update_one(
            {"_id": user_id},
            {"$inc": {"care_subscribe_count": 1}, "$set": {"updated_at": now_cst()}},
        )
    return await get_caring_state(user_id)


async def run_caring_scan() -> dict:
    """扫描一轮候选用户并发送关怀，返回统计。

    候选：未软删、未关闭关怀、仍有订阅配额的用户。模板未配置时安全跳过。
    """
    settings = get_settings()
    stats = {"scanned": 0, "sent": 0, "skipped": 0, "failed": 0}
    if not settings.caring_enabled:
        return stats
    if not settings.wx_subscribe_template_id:
        logger.info("V3 主动关怀：未配置订阅消息模板 ID，本轮跳过（fail-safe）")
        return stats

    cursor = mongo.db[COLL_USERS].find(
        {
            "deleted_at": None,
            "caring_opt_out": {"$ne": True},
            "care_subscribe_count": {"$gt": 0},
        }
    )
    async for user in cursor:
        stats["scanned"] += 1
        try:
            stats[await _send_to_user(user)] += 1
        except Exception:
            logger.exception("V3 主动关怀：处理用户失败 user=%s", user.get("_id"))
            stats["failed"] += 1
    return stats


def _seconds_until_hour(hour: int) -> float:
    """距下一个目标时刻（整点，CST）的秒数；已过则顺延到次日。"""
    now = now_cst()
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_caring_scheduler() -> None:
    """主动关怀后台调度（V3）：每日在 caring_hour 执行一次扫描。

    由 main.lifespan 以 asyncio 任务启动，进程退出时取消；
    单次失败只记日志、不终止循环（次日自动重试）。
    """
    if not get_settings().caring_enabled:
        return
    while True:
        await asyncio.sleep(_seconds_until_hour(get_settings().caring_hour))
        try:
            stats = await run_caring_scan()
            if stats["sent"] or stats["failed"]:
                logger.info("V3 主动关怀扫描完成：%s", stats)
        except Exception:
            logger.exception("V3 主动关怀扫描失败，将于次日重试")
