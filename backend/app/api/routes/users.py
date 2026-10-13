"""用户接口（当前用户信息；删除全部数据属 P4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.responses import ok_response
from app.services import checkins
from app.services import users as users_svc

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """当前用户信息：连续打卡天数 + 基于最近情绪记录生成的记忆型问候（首页用）。"""
    streak = await checkins.compute_streak(current_user["_id"])
    data = users_svc.serialize_me(current_user, checkin_streak=streak)
    data["memory_greeting"] = await checkins.memory_greeting(current_user["_id"])
    return ok_response(data)
