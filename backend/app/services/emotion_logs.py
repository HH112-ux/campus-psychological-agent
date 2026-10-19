"""情绪日志服务（开发文档 F5 / API 文档第 7 节）。

- 时间线：合并"对话来源 emotion_records"与"打卡来源 checkins"，按时间倒序分页；
- 趋势聚合：均值计算全部在服务端完成（小程序只渲染），支持 7/30 天窗口与
  day/week/month 粒度；无记录的日子置 null 不补 0；
- 全部查询强制 user_id 过滤。
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from bson import ObjectId

from app.core.timeutil import CST, to_iso
from app.db.indexes import COLL_CHECKINS, COLL_EMOTION_RECORDS, COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo

# 打卡 mood → 六类情绪枚举（低档映射：low→depressed、irritable→angry），
# 使时间线筛选/趋势主导情绪与对话情绪口径一致（F3 情绪枚举固定六类）
_CHECKIN_EMOTION_MAP = {"low": "depressed", "irritable": "angry"}

_PAGE_SIZE_DEFAULT = 20
_PAGE_SIZE_MAX = 100


def _day_start(d: datetime) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=CST)


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=CST)
    except ValueError:
        return None


async def _collect_emotion_records(user_id: ObjectId, start: datetime, end: datetime):
    cursor = mongo.db[COLL_EMOTION_RECORDS].find(
        {
            "user_id": user_id,
            "created_at": {"$gte": start, "$lt": end},
        }
    )
    return [doc async for doc in cursor]


async def _collect_checkins(user_id: ObjectId, start: datetime, end: datetime):
    cursor = mongo.db[COLL_CHECKINS].find(
        {
            "user_id": user_id,
            "created_at": {"$gte": start, "$lt": end},
        }
    )
    docs = [doc async for doc in cursor]
    # 归一化：补 emotion 键（mood → 六类），供趋势聚合/序列化统一使用
    for d in docs:
        d["emotion"] = _CHECKIN_EMOTION_MAP.get(d.get("mood"), d.get("mood"))
    return docs


async def _session_meta_for(ref_ids: set) -> dict:
    """ref_id（用户消息 id）→ {session_id, title} 映射（message → session 两跳关联）。

    session_id 供日志页"点击时间线条目 → 定位到来源对话"跳转使用。
    """
    if not ref_ids:
        return {}
    msg_ids = {ObjectId(r) for r in ref_ids if r}
    if not msg_ids:
        return {}
    ref_to_session = {
        str(m["_id"]): m.get("session_id")
        async for m in mongo.db[COLL_MESSAGES].find(
            {"_id": {"$in": list(msg_ids)}}, {"session_id": 1}
        )
        if m.get("session_id")
    }
    session_ids = set(ref_to_session.values())
    if not session_ids:
        return {ref: {"session_id": None, "title": None} for ref in ref_to_session}
    titles = {
        str(s["_id"]): s.get("title")
        async for s in mongo.db[COLL_SESSIONS].find(
            {"_id": {"$in": list(session_ids)}}, {"title": 1}
        )
    }
    return {
        ref: {
            "session_id": str(sid),
            "title": titles.get(str(sid)),
        }
        for ref, sid in ref_to_session.items()
    }


def _serialize_record(doc: dict, session_meta: dict) -> dict:
    """对话来源情绪记录 → 时间线条目（session_id 供"定位到来源对话"跳转）。"""
    ref_id = str(doc["ref_id"]) if doc.get("ref_id") else None
    meta = session_meta.get(ref_id, {}) if ref_id else {}
    return {
        "record_id": str(doc["_id"]),
        "source": "message",
        "ref_id": ref_id,
        "session_id": meta.get("session_id"),
        "emotion": doc.get("emotion"),
        "intensity": doc.get("intensity"),
        "evidence": doc.get("evidence"),
        "risk_level": doc.get("risk_level", "none"),
        "session_title": meta.get("title"),
        "created_at": to_iso(doc.get("created_at")) if doc.get("created_at") else None,
    }


def _serialize_checkin(doc: dict) -> dict:
    """打卡来源 → 时间线条目（emotion 归一化为六类；evidence 为 null，附 note 供展示）。"""
    return {
        "record_id": str(doc["_id"]),
        "source": "checkin",
        "ref_id": str(doc["_id"]),
        "emotion": doc.get("emotion") or _CHECKIN_EMOTION_MAP.get(doc.get("mood"), doc.get("mood")),
        "mood": doc.get("mood"),  # 原始打卡档位，供"当日备注编辑"回传
        "intensity": doc.get("intensity"),
        "evidence": None,
        "note": doc.get("note"),
        "risk_level": "none",
        "session_title": None,
        "created_at": to_iso(doc.get("created_at")) if doc.get("created_at") else None,
    }


async def list_records(
    user_id: ObjectId,
    start_date: str | None,
    end_date: str | None,
    emotion: str | None,
    page: int,
    page_size: int,
) -> dict:
    """情绪记录时间线：合并两来源，按 created_at 倒序分页。"""
    now = datetime.now(tz=CST)
    start = _day_start(_parse_date(start_date)) if start_date else now - timedelta(days=30)
    end = (
        _day_start(_parse_date(end_date)) + timedelta(days=1)
        if end_date
        else now + timedelta(days=1)
    )

    emo_docs = await _collect_emotion_records(user_id, start, end)
    checkin_docs = await _collect_checkins(user_id, start, end)

    session_meta = await _session_meta_for(
        {str(d.get("ref_id")) for d in emo_docs if d.get("ref_id")}
    )

    items = [_serialize_record(d, session_meta) for d in emo_docs]
    items.extend(_serialize_checkin(d) for d in checkin_docs)
    if emotion:
        items = [it for it in items if it["emotion"] == emotion]
    items.sort(key=lambda it: it["created_at"] or "", reverse=True)

    total = len(items)
    start_idx = (page - 1) * page_size
    sliced = items[start_idx : start_idx + page_size]
    return {"total": total, "page": page, "page_size": page_size, "items": sliced}


def _to_cst(dt: datetime) -> datetime:
    """统一到业务时区（Asia/Shanghai）。

    motor 从 MongoDB 读回的 datetime 为 **naive UTC**，直接 strftime/hour 会得到
    UTC 值时相（偏差 8 小时，"深夜"记录会被错分到前一天/下午）；此处按 UTC 解释
    后转 CST，已是 aware 的直接转换。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(CST)


def _bucket_key(dt: datetime, granularity: str) -> str:
    dt = _to_cst(dt)  # 先归一到业务时区再分桶，避免 naive UTC 造成的 8 小时偏移
    if granularity == "week":
        # ISO 周（周一为一周开始）
        iso = dt.isocalendar()
        return f"{dt.year}-W{iso.week:02d}"
    if granularity == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def _emotion_count(records: list[dict]) -> tuple[str | None, float | None]:
    if not records:
        return None, None
    counts: dict[str, int] = {}
    for r in records:
        emo = r.get("emotion")
        if emo:
            counts[emo] = counts.get(emo, 0) + 1
    dominant = max(counts, key=counts.get)
    return dominant, counts[dominant] / len(records)


async def get_trends(user_id: ObjectId, days: int, granularity: str) -> dict:
    """趋势聚合：窗口内日均强度、与上一窗口对比、逐日/周/月点、主导情绪。"""
    now = datetime.now(tz=CST)
    window = days if days in (7, 30) else 7
    if granularity not in ("day", "week", "month"):
        granularity = "day"

    cur_start = _day_start(now) - timedelta(days=window - 1)
    cur_end = _day_start(now) + timedelta(days=1)
    prev_start = cur_start - timedelta(days=window)
    prev_end = cur_start

    cur_emo = await _collect_emotion_records(user_id, cur_start, cur_end)
    cur_check = await _collect_checkins(user_id, cur_start, cur_end)
    prev_emo = await _collect_emotion_records(user_id, prev_start, prev_end)
    prev_check = await _collect_checkins(user_id, prev_start, prev_end)

    cur_records = cur_emo + cur_check
    prev_records = prev_emo + prev_check

    def avg(records: list[dict]) -> float | None:
        if not records:
            return None
        return round(sum(r.get("intensity", 0) for r in records) / len(records), 1)

    # 逐桶聚合（无记录的桶 avg=None / dominant=None / count=0，不补 0）
    buckets: dict[str, list[dict]] = {}
    for r in cur_records:
        ts = r.get("created_at")
        if ts:
            key = _bucket_key(ts, granularity)
            buckets.setdefault(key, []).append(r)

    points = []
    if granularity == "day":
        for offset in range(window):
            day = cur_start + timedelta(days=offset)
            key = day.strftime("%Y-%m-%d")
            recs = buckets.get(key, [])
            dominant, _ = _emotion_count(recs)
            points.append(
                {
                    "date": key,
                    "avg_intensity": avg(recs),
                    "dominant": dominant,
                    "count": len(recs),
                }
            )
    else:
        keys = sorted(buckets.keys())
        for key in keys:
            recs = buckets[key]
            dominant, _ = _emotion_count(recs)
            points.append(
                {
                    "date": key,
                    "avg_intensity": avg(recs),
                    "dominant": dominant,
                    "count": len(recs),
                }
            )

    dominant_type, ratio = _emotion_count(cur_records)
    return {
        "window": window,
        "granularity": granularity,
        "avg_intensity": avg(cur_records),
        "prev_avg_intensity": avg(prev_records),
        "points": points,
        "dominant_emotion": (
            {"type": dominant_type, "ratio": round(ratio, 2)} if dominant_type else None
        ),
    }


# ---------- V2 周报洞察 ----------

# 时段归类（按业务时区小时划分）：早上 5–11 / 下午 12–17 / 晚上 18–22 / 深夜 23–4
_PERIOD_ORDER = ("morning", "afternoon", "evening", "night")
_PERIOD_LABELS = {"morning": "早上", "afternoon": "下午", "evening": "晚上", "night": "深夜"}

# 六类情绪 → 中文标签（周报文案用）
_EMOTION_LABELS = {
    "calm": "平静",
    "ok": "还行",
    "anxious": "焦虑",
    "depressed": "低落",
    "angry": "烦躁",
    "other": "其他",
}


def _period_key(dt: datetime) -> str:
    hour = _to_cst(dt).hour
    if hour < 5:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    if hour < 23:
        return "evening"
    return "night"


def _records_avg(records: list[dict]) -> float | None:
    if not records:
        return None
    return round(sum(r.get("intensity", 0) for r in records) / len(records), 1)


async def get_weekly_insight(user_id: ObjectId, days: int = 7) -> dict:
    """V2 周报洞察：基于既有趋势聚合生成描述性「本周情绪小结」。

    红线（roadmap §V2）：只输出**描述性**结论（如「本周焦虑多出现在晚上」），
    严禁归因断言——不出现「因为 / 导致 / 由于」类因果句式，不替用户解释成因。
    无记录时返回 has_data=false 与一句引导文案，不报错。
    """
    now = datetime.now(tz=CST)
    window = days if days in (7, 30) else 7
    cur_start = _day_start(now) - timedelta(days=window - 1)
    cur_end = _day_start(now) + timedelta(days=1)
    prev_start = cur_start - timedelta(days=window)

    cur_emo = await _collect_emotion_records(user_id, cur_start, cur_end)
    cur_check = await _collect_checkins(user_id, cur_start, cur_end)
    prev_records = await _collect_emotion_records(
        user_id, prev_start, cur_start
    ) + await _collect_checkins(user_id, prev_start, cur_start)
    cur_records = cur_emo + cur_check

    base = {
        "window_days": window,
        "start_date": cur_start.strftime("%Y-%m-%d"),
        "end_date": (cur_end - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    avg_prev = _records_avg(prev_records)

    if not cur_records:
        return {
            **base,
            "has_data": False,
            "record_count": 0,
            "record_days": 0,
            "checkin_days": 0,
            "avg_intensity": None,
            "prev_avg_intensity": avg_prev,
            "intensity_trend": "none",
            "dominant_emotion": None,
            "peak_period": None,
            "peak_period_label": None,
            "period_counts": {},
            "highlights": [f"近 {window} 天还没有情绪记录，聊聊天或打个卡就有了。"],
        }

    avg_cur = _records_avg(cur_records)
    trend = "none"
    if avg_cur is not None and avg_prev is not None:
        diff = round(avg_cur - avg_prev, 1)
        trend = "flat" if abs(diff) < 0.5 else ("up" if diff > 0 else "down")

    dominant_type, ratio = _emotion_count(cur_records)
    dominant_label = _EMOTION_LABELS.get(dominant_type, dominant_type)

    record_days = {
        _to_cst(r["created_at"]).strftime("%Y-%m-%d")
        for r in cur_records
        if r.get("created_at")
    }
    checkin_days = len({c.get("date") for c in cur_check if c.get("date")})

    period_counts = Counter(
        _period_key(r["created_at"]) for r in cur_records if r.get("created_at")
    )
    # 主导情绪的时段分布：找它出现最多的时段（并列时取更早时段，保持确定性）
    dom_period_counts = Counter(
        _period_key(r["created_at"])
        for r in cur_records
        if r.get("created_at") and r.get("emotion") == dominant_type
    )
    peak_period = None
    if dom_period_counts:
        peak_period = max(
            dom_period_counts,
            key=lambda k: (dom_period_counts[k], -_PERIOD_ORDER.index(k)),
        )

    highlights: list[str] = [
        f"近 {window} 天你记录了 {len(record_days)} 天、共 {len(cur_records)} 条情绪记录。"
    ]
    if dominant_type:
        highlights.append(f"本周以「{dominant_label}」为主（占 {round((ratio or 0) * 100)}%）。")
        if peak_period:
            highlights.append(f"「{dominant_label}」多出现在{_PERIOD_LABELS[peak_period]}。")
    if trend == "down":
        highlights.append(f"整体情绪强度比上周略有下降（{avg_prev} → {avg_cur}）。")
    elif trend == "up":
        highlights.append(f"整体情绪强度比上周略有上升（{avg_prev} → {avg_cur}）。")
    elif trend == "flat":
        highlights.append("整体情绪强度与上周基本持平。")
    if checkin_days > 0:
        highlights.append(f"本周打卡 {checkin_days} 天。")

    return {
        **base,
        "has_data": True,
        "record_count": len(cur_records),
        "record_days": len(record_days),
        "checkin_days": checkin_days,
        "avg_intensity": avg_cur,
        "prev_avg_intensity": avg_prev,
        "intensity_trend": trend,
        "dominant_emotion": (
            {"type": dominant_type, "ratio": round(ratio, 2)} if dominant_type else None
        ),
        "peak_period": peak_period,
        "peak_period_label": _PERIOD_LABELS.get(peak_period) if peak_period else None,
        "period_counts": dict(period_counts),
        "highlights": highlights,
    }
