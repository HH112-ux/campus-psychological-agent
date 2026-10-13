"""危机求助资源接口（公开，无需登录——公共安全信息）。"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.responses import ok_response
from app.services.crisis import get_resources

router = APIRouter(prefix="/api/v1/crisis", tags=["crisis"])


@router.get("/resources")
async def crisis_resources():
    return ok_response(await get_resources())
