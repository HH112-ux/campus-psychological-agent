"""用户数据集合登记表（PIPL 数据导出 / 物理删除的**唯一权威来源**）。

背景：`services/privacy.py` 此前在 `export_user_data()` 与 `purge_expired_data()`
两处各自硬编码集合清单。V3/V4/V6 每新增一个数据能力，都要同时改这两处；
漏改任一处即导致「导出缺失」或更严重的「到期漏删」——后者直接违背
「软删 N 天后物理删除」的对外承诺，属合规风险而非风格问题。

本表把清单收敛为单一来源，并配合测试断言「登记表内每个集合都被导出与删除覆盖」。

- owner="user"：直接按 `user_id` 归属；
- owner="via_sessions"：随会话归属（消息按 `session_id` 关联，依赖会话 id 列表）。

说明：删除完全由本表驱动；导出因各集合字段投影不同（对外契约），沿用各自
投影实现，其覆盖性由测试保证。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.db.indexes import (
    COLL_CARE_MESSAGES,
    COLL_CHECKINS,
    COLL_EMOTION_RECORDS,
    COLL_MEMORIES,
    COLL_MESSAGES,
    COLL_PRACTICE_LOGS,
    COLL_RISK_EVENTS,
    COLL_SESSIONS,
)

OWNER_USER = "user"
OWNER_VIA_SESSIONS = "via_sessions"


@dataclass(frozen=True)
class UserDataCollection:
    """登记项：集合名 + 归属方式。集合名与导出的 JSON 字段名一致。"""

    name: str
    owner: str = OWNER_USER


# 用户数据集合（不含 users：用户文档在导出/删除中单独处理，删除须排在其后）
USER_DATA_COLLECTIONS: tuple[UserDataCollection, ...] = (
    UserDataCollection(COLL_SESSIONS),
    UserDataCollection(COLL_MESSAGES, owner=OWNER_VIA_SESSIONS),
    UserDataCollection(COLL_EMOTION_RECORDS),
    UserDataCollection(COLL_CHECKINS),
    UserDataCollection(COLL_RISK_EVENTS),
    UserDataCollection(COLL_CARE_MESSAGES),
    UserDataCollection(COLL_PRACTICE_LOGS),
    UserDataCollection(COLL_MEMORIES),
)

# 导出 JSON 中必须出现的字段名（供覆盖测试断言 export ⊇ 登记表）
EXPORT_KEYS: tuple[str, ...] = tuple(c.name for c in USER_DATA_COLLECTIONS)
