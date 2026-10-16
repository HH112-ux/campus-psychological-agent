"""应用配置：从环境变量 / .env 加载，密钥一律不入库。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，字段与 .env.example 一一对应。"""

    # 应用
    app_name: str = "xinyu-backend"
    app_version: str = "0.2.0"
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

    # 微信小程序（P1 登录链路）
    wx_appid: str = ""
    wx_secret: str = ""
    # 开发期 mock 登录：为 true 时不调微信，用 code 确定性派生 openid；生产必须为 false
    wx_mock_login: bool = True
    # mock 模式下固定的开发用户 openid（模拟同一台设备同一用户；测多用户可覆盖）
    wx_mock_openid: str = "mock_dev_openid"
    wx_code2session_url: str = "https://api.weixin.qq.com/sns/jscode2session"

    # 内容安全（M1 / G9，提审要求）：用户消息入库前过微信 msgSecCheck
    # mock 登录或未配置 AppID/Secret 时自动跳过（dev 不阻塞）；生产必须为 true
    wx_content_check_enabled: bool = True
    wx_stable_token_url: str = "https://api.weixin.qq.com/cgi-bin/stable_token"
    wx_msg_sec_check_url: str = "https://api.weixin.qq.com/wxa/msg_sec_check"

    # 业务规则（P1）
    message_max_length: int = 2000
    session_round_limit: int = 50
    # 并发活跃会话上限：对外契约（README / API 文档 / .env.example）一致为 5
    # （M6 先对齐为 3，UX 评估后调整为 5：兼顾多话题并行体验与成本/内存控制）
    session_concurrency_limit: int = 5
    memory_window_rounds: int = 20  # 窗口记忆：近 20 轮（约 40 条消息）
    session_messages_max_return: int = 200  # 会话详情最多返回最近 200 条

    # 数据留存与清除（M3，见 docs/improvement-roadmap.md）
    # 软删后用户可撤销的天数；期满由后台定时任务物理删除
    erase_recover_days: int = 30  # 期限口径待 M2（校方）确认后调整
    # 必须为 true，否则「软删 N 天后物理删除」的合规承诺不兑现（G7）
    data_purge_enabled: bool = True
    data_purge_interval_seconds: int = 3600  # 到期数据扫描间隔（秒），默认每小时一次

    # 智谱开放平台（P0 需跑通一次调用）
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model_chat: str = "glm-4-air"  # 主对话档
    model_light: str = "glm-4-flash"  # 轻量档（情绪分析）

    # 限流与降级
    user_message_hourly_limit: int = 30
    model_timeout_seconds: float = 30.0

    # 情绪分析（P3）：单轮分析硬超时，超过即跳过本轮记录（保证 done 不被长期阻塞）
    emotion_analysis_timeout_seconds: float = 5.0
    # P5 降级开关：情绪分析整体可关（关后不调用轻量模型、不写情绪记录、不发 emotion 事件）
    emotion_analysis_enabled: bool = True
    # P5 降级开关：流式可关（关后对话统一走非流式 JSON 路径，弱网/平台异常时兜底）
    stream_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
