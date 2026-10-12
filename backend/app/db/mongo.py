"""MongoDB 连接管理（motor 异步驱动）。"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings


class MongoManager:
    """持有全局 client 与 db；连接失败不抛异常，状态由 /health 暴露。"""

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        settings = get_settings()
        try:
            self._client = AsyncIOMotorClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
            )
            # 触发一次连接探测
            await self._client.admin.command("ping")
            self._db = self._client[settings.mongodb_db]
        except Exception:
            # 本地无 MongoDB 时服务仍可启动（/health 报告 disconnected）
            self._client = None
            self._db = None

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None

    @property
    def db(self) -> AsyncIOMotorDatabase | None:
        return self._db

    @property
    def is_connected(self) -> bool:
        return self._db is not None


mongo = MongoManager()
