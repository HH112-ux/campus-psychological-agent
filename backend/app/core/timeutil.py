"""时间工具：统一以 Asia/Shanghai（UTC+8）为业务时区，ISO 8601 输出。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_cst() -> datetime:
    """当前上海时间（带时区）。"""
    return datetime.now(tz=CST)


def to_iso(dt: datetime) -> str:
    """格式化为带时区的 ISO 8601 字符串，如 2026-10-12T23:47:03+08:00。"""
    return dt.astimezone(CST).isoformat(timespec="seconds")


def date_str(dt: datetime | None = None) -> str:
    """返回 yyyymmdd 风格的日期串（这里用 yyyy-mm-dd，便于唯一索引与人读）。"""
    return (dt or now_cst()).astimezone(CST).strftime("%Y-%m-%d")
