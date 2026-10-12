"""应用配置：从环境变量 / .env 加载，密钥一律不入库。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，字段与 .env.example 一一对应。"""

    # 应用
    app_name: str = "xinyu-backend"
    app_version: str = "0.1.0"
    env: str = "dev"  # dev | prod
    debug: bool = False

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "xinyu"

    # 安全（P1 起启用，P0 先占位）
    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    access_token_expire_seconds: int = 7 * 24 * 3600
    refresh_token_expire_seconds: int = 30 * 24 * 3600

    # 数据加密（P4 起启用）
    data_encryption_key: str = ""

    # 智谱开放平台（P0 需跑通一次调用）
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model_chat: str = "glm-4-air"  # 主对话档
    model_light: str = "glm-4-flash"  # 轻量档（情绪分析）

    # 限流与降级
    user_message_hourly_limit: int = 30
    model_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
