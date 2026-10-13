"""FastAPI 应用入口。

P0 验收：GET /health 返回 200；服务可启动（DB 未连接时降级报告状态）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, crisis, emotion, health, messages, sessions, users
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.db.mongo import mongo


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.connect()
    yield
    await mongo.disconnect()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="心屿 · 校园心理咨询智能陪伴 Agent 后端",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    # 危机资源为公开接口，与健康检查一样无需鉴权；其余路由内部强制 JWT
    app.include_router(health.router)
    app.include_router(crisis.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(emotion.router)
    return app


app = create_app()
