"""用户接口（P1：当前用户信息；删除全部数据属 P4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.responses import ok_response
from app.services import users as users_svc

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return ok_response(users_svc.serialize_me(current_user))
