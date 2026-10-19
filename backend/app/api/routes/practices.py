"""练习卡片接口（V4：目录 + 完成反馈，对齐 API 文档第 9 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.exceptions import CODE_NOT_FOUND, BizError
from app.core.responses import ok_response
from app.models.practice import PracticeCompleteRequest
from app.services import practices

router = APIRouter(prefix="/api/v1/practices", tags=["practices"])


@router.get("")
async def list_practices(current_user: dict = Depends(get_current_user)):
    """练习卡片目录（含今日已完成标记）。"""
    return ok_response(await practices.list_practices(current_user["_id"]))


@router.post("/{practice_id}/complete")
async def complete_practice(
    practice_id: str,
    body: PracticeCompleteRequest,
    current_user: dict = Depends(get_current_user),
):
    """记录一次练习完成（未知练习返回 2001）。"""
    result = await practices.complete_practice(
        current_user["_id"], practice_id, body.duration_seconds
    )
    if result is None:
        raise BizError(CODE_NOT_FOUND, "练习不存在", http_status=404)
    return ok_response(result)
