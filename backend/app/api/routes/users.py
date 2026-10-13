"""用户接口（当前用户信息、隐私同意、数据导出、数据删除）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.exceptions import CODE_BUSINESS_VALIDATION, BizError
from app.core.responses import ok_response
from app.models.auth import ConsentRequest, EraseRequest
from app.services import checkins
from app.services import privacy as privacy_svc
from app.services import users as users_svc

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """当前用户信息：连续打卡天数 + 基于最近情绪记录生成的记忆型问候（首页用）。"""
    streak = await checkins.compute_streak(current_user["_id"])
    data = users_svc.serialize_me(current_user, checkin_streak=streak)
    data["memory_greeting"] = await checkins.memory_greeting(current_user["_id"])
    return ok_response(data)


@router.post("/me/consent")
async def consent(body: ConsentRequest, current_user: dict = Depends(get_current_user)):
    """P4 隐私同意：记录用户对隐私政策的单独同意。"""
    if not body.agree:
        raise BizError(CODE_BUSINESS_VALIDATION, "需要同意隐私政策才能继续使用", http_status=400)
    result = await privacy_svc.record_consent(
        current_user["_id"], body.policy_version
    )
    return ok_response(result, message="已记录同意")


@router.get("/me/data/export")
async def export_data(current_user: dict = Depends(get_current_user)):
    """P4 数据导出：导出用户全部数据为 JSON（PIPL 行权）。"""
    data = await privacy_svc.export_user_data(current_user["_id"])
    return ok_response(data)


@router.delete("/me/data")
async def erase_data(body: EraseRequest, current_user: dict = Depends(get_current_user)):
    """P4 数据删除：软删 30 天后物理删除，立即生效。"""
    if body.confirm_text != "删除":
        raise BizError(CODE_BUSINESS_VALIDATION, '请输入"删除"以确认', http_status=400)
    result = await privacy_svc.erase_user_data(current_user["_id"])
    return ok_response(result, message="已删除，30 天内登录可撤销")
