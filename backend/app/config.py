"""应用配置：从环境变量 / .env 加载，密钥一律不入库。"""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.crisis_data import phone_problems


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
    # 密钥版本化（轮换用）：新密文信封写入该 id 便于审计；轮换时把旧钥配到 previous，
    # 旧数据仍可解密（写入统一用当前钥），全部重写完成后再移除 previous。
    data_encryption_key_id: str = "v1"
    data_encryption_key_previous: str = ""

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

    # 跨实例共享状态后端（M5/G4）：memory=单机内存（dev/默认）；redis=多实例共享（生产）
    # 同时驱动限流（ratelimit）、告警冷却与失败率计数（counter），故名 shared_state_backend；
    # 旧名 RATELIMIT_BACKEND 仍可作为环境变量读取（别名兼容，勿在新配置中使用）
    shared_state_backend: str = Field(
        default="memory",
        validation_alias=AliasChoices("shared_state_backend", "ratelimit_backend"),
    )
    redis_url: str = "redis://localhost:6379/0"

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

    # E2 多模型容灾：通义千问备用供应商（OpenAI 兼容接口）
    # qwen_enabled=true 且 qwen_api_key 非空时启用；主 provider 异常自动切备用
    qwen_enabled: bool = False
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model_chat: str = "qwen-plus"  # 备用主档（与 glm-4-air 同等级）
    qwen_model_light: str = "qwen-turbo"  # 备用轻量档（与 glm-4-flash 同等级）

    # E3 模型路由与成本基线（默认关闭路由，保持现有行为不变）
    # 启发式分流：短句 + 无危机 + 非负面情绪 → 轻量档；其余走主档（零额外 LLM 调用）
    cost_routing_enabled: bool = False
    cost_routing_light_max_chars: int = 30  # 超过此长度视为复杂疏导，走主档
    # 成本基线：按档位累计调用次数与字符数，输出结构化日志（进程内估算，不做看板）
    cost_tracking_enabled: bool = True

    # 限流与降级
    user_message_hourly_limit: int = 30
    model_timeout_seconds: float = 30.0

    # 情绪分析（P3）：单轮分析硬超时，超过即跳过本轮记录（保证 done 不被长期阻塞）
    emotion_analysis_timeout_seconds: float = 5.0
    # P5 降级开关：情绪分析整体可关（关后不调用轻量模型、不写情绪记录、不发 emotion 事件）
    emotion_analysis_enabled: bool = True
    # P5 降级开关：流式可关（关后对话统一走非流式 JSON 路径，弱网/平台异常时兜底）
    stream_enabled: bool = True
    # SSE 心跳间隔：需小于小程序端 idle 超时（10s），否则首包慢会被误判为断线
    sse_heartbeat_seconds: float = 5.0

    # 监控告警（M5 ③ / M4 值班人通知）：企业微信群机器人 webhook
    # 未配置 alert_webhook_url 时仅记 warning 日志（dev 默认）；异常永不阻断主链路
    alert_enabled: bool = True
    alert_webhook_url: str = ""
    # 同一告警 key 的 webhook 冷却时间（秒），防止重复轰炸；日志不受冷却影响
    alert_cooldown_seconds: int = 600

    # 主动关怀（V3）：连续低落 / 打卡中断 → 次日经微信订阅消息温和问候（用户可随时关闭）
    caring_enabled: bool = True
    caring_low_streak_days: int = 3  # 连续 N 天低落（low/anxious/irritable）触发关怀
    caring_checkin_gap_days: int = 2  # 打卡中断 N 天（有历史记录但近期未打卡）触发关怀
    caring_max_per_week: int = 2  # 频控：同一用户每周最多发送条数
    caring_hour: int = 9  # 每日扫描/发送时刻（Asia/Shanghai，0–23）
    # 订阅消息模板 ID（微信侧外部依赖）：未配置时扫描安全跳过，不影响主链路与调度
    wx_subscribe_template_id: str = ""
    # 模板中承载问候语的字段名（微信模板 data 字段，如 thing1）；thing 类型限 20 字符
    wx_subscribe_field_key: str = "thing1"
    wx_subscribe_send_url: str = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"

    # 语音入口（V5）：小程序录音 → 转写 → 用户确认后进入对话
    # 合规基线（M3 预案）：转写后即弃、不落原始音频；提供方未配置时 fail-safe 降级为键盘输入
    asr_enabled: bool = True
    asr_provider: str = "mock"  # mock=本地联调占位（生产禁用）；http=调用通用 ASR 网关
    # 通用 ASR 网关：POST 原始音频字节，期望返回 {"text": "..."}
    asr_endpoint_url: str = ""
    asr_api_key: str = ""
    asr_timeout_seconds: float = 15.0
    asr_max_audio_bytes: int = 2 * 1024 * 1024  # 单段录音体积上限（约 2MB；前端同步限时长 60s）
    asr_mock_text: str = "这是一段语音输入的内容"  # mock 提供方固定返回（仅本地联调）

    # 长期记忆（V6）：跨会话记住人物/事件/偏好/情绪诱因，回复时按相关性克制注入
    # 总开关关闭时不抽取、不注入（已存记忆仍可在「我的」中查看与删除）
    long_memory_enabled: bool = True
    # 抽取调用硬超时（秒），超过即跳过本轮（抽取在后台任务中执行，不阻塞回复）
    long_memory_extract_timeout_seconds: float = 8.0
    # 单用户记忆条数上限，超出丢弃最旧的（最小化留存）
    long_memory_max_items: int = 100
    # 注入克制：单轮最多带入条数与总字数上限
    long_memory_inject_max_items: int = 5
    long_memory_inject_max_chars: int = 200

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    @model_validator(mode="after")
    def _validate_prod_config(self) -> Settings:
        """生产环境启动校验（M5 ⑤，G11 类风险）：危险/缺失配置直接拒绝启动。

        仅 env=prod 生效；dev/测试（默认 env=dev）不受影响。
        """
        # 方向性校验先行：任何非 dev 环境都不允许 mock 登录。
        # mock 模式下所有请求都映射到同一个固定 openid，一旦上线会让全校共用一个账号。
        if self.env != "dev" and self.wx_mock_login:
            raise ValueError(
                "生产配置校验未通过：\n- WX_MOCK_LOGIN 必须为 false"
                f"（env={self.env} 禁止 mock 登录，否则所有用户共用同一个 openid）"
            )
        if self.env != "prod":
            return self
        problems: list[str] = []
        if not self.wx_appid or not self.wx_secret:
            problems.append("WX_APPID / WX_SECRET 必须配置（真实登录与内容安全链路依赖）")
        if not self.wx_content_check_enabled:
            problems.append("WX_CONTENT_CHECK_ENABLED 必须为 true（G9，提审与合规要求）")
        if self.jwt_secret in ("", "change-me-in-env") or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET 必须更换为 ≥32 位随机串（不得使用默认值）")
        if not self.data_encryption_key:
            problems.append("DATA_ENCRYPTION_KEY 必须配置（对话内容 AES-256-GCM 应用层加密）")
        mongo_uri = urlsplit(self.mongodb_uri)
        if not mongo_uri.username or not mongo_uri.password:
            problems.append(
                "MONGODB_URI 必须包含用户名/密码（生产禁止无认证连接，见 docker-compose.yml）"
            )
        if not self.zhipu_api_key:
            problems.append("ZHIPU_API_KEY 必须配置（对话主链路依赖）")
        # 求助资源电话：不允许为空或明显非法（号码由校方提供，不做占位符识别）
        problems.extend(phone_problems())
        if self.asr_enabled:
            if self.asr_provider == "mock":
                problems.append("ASR_PROVIDER 不能为 mock（生产禁止假转写），请配置 http 网关")
            elif self.asr_provider != "http":
                problems.append(f"ASR_PROVIDER 非法值：{self.asr_provider}（仅支持 http）")
            elif not self.asr_endpoint_url or not self.asr_api_key:
                problems.append("ASR_ENDPOINT_URL / ASR_API_KEY 必须配置（ASR_PROVIDER=http 依赖）")
        if problems:
            raise ValueError("生产配置校验未通过：\n- " + "\n- ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
