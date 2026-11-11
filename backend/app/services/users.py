"""用户服务：openid 主键、令牌旋转状态、对外序列化（openid 永不外泄）。"""
from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.core.timeutil import now_cst, to_iso
from app.db.indexes import COLL_USERS
from app.db.mongo import mongo
from app.db.oid import parse_oid
from app.services.privacy import purge_user_data, recover_user


async def get_or_create_by_openid(
    openid: str, nickname: str | None = None, avatar: str | None = None
) -> tuple[dict, bool]:
    """按 openid 查找或创建用户，返回 (用户文档, 是否新用户)。

    openid 唯一索引会被软删记录占用，因此「查不到活跃用户」时还要区分：
    - 恢复期内（erase_at 未到）再次登录：撤销软删，接回同一身份（30 天承诺）；
    - 已过恢复期：先物理删除旧身份全部数据，再以同一 openid 注册新身份。
    """
    coll = mongo.db[COLL_USERS]
    user = await coll.find_one({"openid": openid, "deleted_at": None})
    if user is None:
        deleted = await coll.find_one({"openid": openid})
        if deleted is not None:
            # 恢复期判定交给 Mongo 查询，避免 Python 侧 aware/naive 时区比较差异
            expired = await coll.find_one(
                {"_id": deleted["_id"], "erase_at": {"$lte": now_cst()}}
            )
            if expired is not None:
                await purge_user_data(expired)
            else:
                await recover_user(deleted["_id"])
                user = await coll.find_one(
                    {"_id": deleted["_id"], "deleted_at": None}
                )
    if user:
        # 若本次带了昵称/头像（用户授权），顺手更新
        update: dict = {}
        if nickname and not user.get("nickname"):
            update["nickname"] = nickname
        if avatar and not user.get("avatar"):
            update["avatar"] = avatar
        if update:
            update["updated_at"] = now_cst()
            await coll.update_one({"_id": user["_id"]}, {"$set": update})
            user.update(update)
        return user, False

    now = now_cst()
    doc = {
        "openid": openid,
        "nickname": nickname,
        "avatar": avatar,
        "consent_at": None,  # 隐私单独同意在 P4 弹窗流程写入
        "current_refresh_jti": None,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    try:
        result = await coll.insert_one(doc)
    except DuplicateKeyError:
        # 并发首登：另一请求已先插入（或刚完成恢复），回读同一身份即可
        existing = await coll.find_one({"openid": openid, "deleted_at": None})
        if existing is None:
            raise
        return existing, False
    doc["_id"] = result.inserted_id
    return doc, True


async def get_by_id(user_id: str) -> dict | None:
    # P-15：令牌合法但 sub 非法时，应表现为"未登录"（401）而非"资源不存在"（404），
    # 避免客户端按 401 重登录的逻辑失效。非法 ObjectId 一律按"查无此人"处理。
    try:
        oid = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None
    return await mongo.db[COLL_USERS].find_one(
        {"_id": oid, "deleted_at": None}
    )


async def set_refresh_jti(user_id: str | ObjectId, jti: str) -> None:
    await mongo.db[COLL_USERS].update_one(
        {"_id": user_id if isinstance(user_id, ObjectId) else parse_oid(user_id)},
        {"$set": {"current_refresh_jti": jti, "updated_at": now_cst()}},
    )


def serialize_me(user: dict, checkin_streak: int = 0) -> dict:
    """GET /users/me 出参（不含 openid）。"""
    return {
        "user_id": str(user["_id"]),
        "nickname": user.get("nickname"),
        "avatar_url": user.get("avatar"),
        "consented": bool(user.get("consent_at")),
        "checkin_streak": checkin_streak,  # P3 打卡上线后计算
        "created_at": to_iso(user.get("created_at")) if user.get("created_at") else None,
    }
