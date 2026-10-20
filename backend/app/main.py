"""FastAPI 应用入口。

P0 验收：GET /health 返回 200；服务可启动（DB 未连接时降级报告状态）。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.routes import (
    auth,
    crisis,
    emotion,
    health,
    memory,
    messages,
    practices,
    sessions,
    speech,
    users,
)
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.ratelimit import close_redis_client
from app.db.mongo import mongo
from app.services import caring as caring_svc
from app.services import privacy as privacy_svc

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.connect()
    settings = get_settings()
    if settings.env == "prod" and settings.ratelimit_backend != "redis":
        # 生产多实例下内存限流各实例独立计数、形同虚设（G4）；不阻断启动，但必须可见
        logger.warning("生产环境 RATELIMIT_BACKEND 非 redis，限流计数不跨实例共享")
    # M3：到期数据物理删除必须真实生效（G7），否则「软删 N 天后物理删除」的合规承诺不兑现
    purge_task = (
        asyncio.create_task(privacy_svc.run_purge_scheduler())
        if settings.data_purge_enabled and mongo.is_connected
        else None
    )
    # V3：主动关怀每日扫描（未配置订阅模板 ID 时安全跳过，不阻塞主链路）
    caring_task = (
        asyncio.create_task(caring_svc.run_caring_scheduler())
        if settings.caring_enabled and mongo.is_connected
        else None
    )
    try:
        yield
    finally:
        for task in (purge_task, caring_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await close_redis_client()
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
    app.include_router(practices.router)
    app.include_router(speech.router)
    app.include_router(memory.router)
    return app


app = create_app()
