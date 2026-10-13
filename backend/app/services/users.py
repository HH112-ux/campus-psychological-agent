"""用户服务：openid 主键、令牌旋转状态、对外序列化（openid 永不外泄）。"""
from __future__ import annotations

from bson import ObjectId

from app.core.timeutil import now_cst, to_iso
from app.db.indexes import COLL_USERS
from app.db.mongo import mongo
from app.db.oid import parse_oid


async def get_or_create_by_openid(
    openid: str, nickname: str | None = None, avatar: str | None = None
) -> tuple[dict, bool]:
    """按 openid 查找或创建用户，返回 (用户文档, 是否新用户)。"""
    coll = mongo.db[COLL_USERS]
    user = await coll.find_one({"openid": openid, "deleted_at": None})
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
    result = await coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc, True


async def get_by_id(user_id: str) -> dict | None:
    return await mongo.db[COLL_USERS].find_one(
        {"_id": parse_oid(user_id), "deleted_at": None}
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
