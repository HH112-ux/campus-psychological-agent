"""健康检查路由：GET /health（P0 验收项）。"""
from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.core.responses import ok_response
from app.db.mongo import mongo

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    data = {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "env": settings.env,
        "db": "connected" if mongo.is_connected else "disconnected",
    }
    return ok_response(data)
