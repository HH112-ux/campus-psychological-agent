"""W1 登记表覆盖性测试：PIPL 导出与物理删除不得漏任何用户数据集合。

背景：`services/privacy.py` 曾在 `export_user_data()` 与 `purge_expired_data()`
两处各自硬编码集合清单，V3/V4/V6 每新增一个数据能力都要改两处，漏改即合规风险
（导出缺失 / 更严重的「到期漏删」）。现收敛到 `app.db.user_data_registry`，
本测试锁死两点契约：

1. 导出 JSON 的字段 ⊇ 登记表集合名（`export ⊇ registry`）；
2. `purge_expired_data()` 删除登记表内**每个**集合的数据（含此前未被
   `test_privacy.py::test_purge_expired_data` 覆盖的 care_messages /
   practice_logs / memories）。

依赖 MongoDB（通过 conftest 的 client fixture 自动 skip）。
"""
from __future__ import annotations

from tests.helpers import create_session, login


def test_registry_names_unique_and_excludes_users():
    """静态契约：集合名唯一，且 users 不在表内（用户文档导出/删除单独处理，删除须排最后）。"""
    from app.db.indexes import COLL_USERS
    from app.db.user_data_registry import USER_DATA_COLLECTIONS

    names = [c.name for c in USER_DATA_COLLECTIONS]
    assert len(names) == len(set(names)), "登记表集合名不得重复"
    assert COLL_USERS not in names, "users 由导出/删除单独处理（删除须排在最后）"


def test_export_covers_every_registered_collection(client, db):
    """导出 JSON 字段必须覆盖登记表每个集合（否则「导出缺失」）。"""
    from app.db.indexes import COLL_USERS
    from app.db.mongo import mongo
    from app.db.user_data_registry import EXPORT_KEYS
    from app.services.privacy import export_user_data

    login(client, "mock_registry_user")

    async def run():
        user = await mongo.db[COLL_USERS].find_one({"openid": "mock_registry_user"})
        assert user is not None
        data = await export_user_data(user["_id"])
        return set(data.keys())

    keys = client.portal.call(run)
    missing = set(EXPORT_KEYS) - keys
    assert not missing, f"导出缺失登记集合字段：{missing}"
    # 用户文档与导出时间戳单独出现（不在登记表中）
    assert {"user", "exported_at"} <= keys


def test_purge_removes_every_registered_collection(client, db):
    """物理删除必须清空登记表内每个集合：注入 → 到期 → purge → 全为 0。

    覆盖 test_privacy.py 未涉及的 care_messages / practice_logs / memories，
    确保「软删 N 天后物理删除」对外承诺对**所有**数据集合成立。
    """
    from datetime import timedelta

    from app.core.timeutil import now_cst
    from app.db.indexes import COLL_SESSIONS, COLL_USERS
    from app.db.mongo import mongo
    from app.db.user_data_registry import (
        OWNER_VIA_SESSIONS,
        USER_DATA_COLLECTIONS,
    )
    from app.services.privacy import purge_expired_data

    token = login(client, "mock_registry_user")
    create_session(client, token)

    async def run():
        user = await mongo.db[COLL_USERS].find_one({"openid": "mock_registry_user"})
        uid = user["_id"]
        session_ids = [
            s["_id"]
            async for s in mongo.db[COLL_SESSIONS].find({"user_id": uid}, {"_id": 1})
        ]
        assert session_ids, "前置：用户应持有会话，消息（via_sessions）删除路径才被覆盖"
        sid = session_ids[0]

        # 为登记表每个集合注入一条数据（messages 按 session_id 归属，其余按 user_id）
        for entry in USER_DATA_COLLECTIONS:
            if entry.owner == OWNER_VIA_SESSIONS:
                await mongo.db[entry.name].insert_one({"session_id": sid})
            else:
                await mongo.db[entry.name].insert_one({"user_id": uid})

        # 标记为已过恢复期 → 触发物理删除
        await mongo.db[COLL_USERS].update_one(
            {"_id": uid},
            {"$set": {"deleted_at": now_cst(), "erase_at": now_cst() - timedelta(seconds=1)}},
        )
        purged = await purge_expired_data()
        assert purged == 1, "到期用户应被物理删除且计数为 1"

        remaining: dict[str, int] = {}
        for entry in USER_DATA_COLLECTIONS:
            if entry.owner == OWNER_VIA_SESSIONS:
                remaining[entry.name] = await mongo.db[entry.name].count_documents(
                    {"session_id": {"$in": session_ids}}
                )
            else:
                remaining[entry.name] = await mongo.db[entry.name].count_documents(
                    {"user_id": uid}
                )
        users_left = await mongo.db[COLL_USERS].count_documents({"_id": uid})
        return remaining, users_left

    remaining, users_left = client.portal.call(run)
    assert all(v == 0 for v in remaining.values()), f"存在未清理集合：{remaining}"
    assert users_left == 0, "用户文档应被物理删除"
