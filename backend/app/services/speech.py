"""语音转写服务（V5）。

小程序录音 → 本服务转写为文字 → 回到对话（用户确认可编辑后再作为普通消息发送）。

合规基线（roadmap M3 预案，硬约束）：
- **转写后即弃、不落原始音频**——音频只在内存中转发给 ASR 提供方，不写数据库、不落磁盘；
- 日志只记长度与结果状态，不含音频与转写原文。

提供方（`ASR_PROVIDER`）：
- `mock`：本地联调占位（返回固定提示文本），**生产启动校验禁止**；
- `http`：调用配置的通用 ASR 网关（`ASR_ENDPOINT_URL`，POST 原始音频字节，期望 `{"text": "..."}`）。

fail-safe：`ASR_ENABLED=false` / 提供方未配置 / 转写失败 时抛明确业务错误（code=5001），
前端据此降级回键盘输入，不阻断主链路（与 V3 未配置模板 ID 的取舍一致）。
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.core.exceptions import CODE_BUSINESS_VALIDATION, BizError

logger = logging.getLogger(__name__)

# 支持的音频容器（微信 RecorderManager 产出 mp3/aac；另兼容常见类型）
_ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/aac",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
    "application/octet-stream",
}


def _degrade(message: str) -> BizError:
    """统一的「降级为键盘输入」业务错误（前端按 message 直接提示）。"""
    return BizError(CODE_BUSINESS_VALIDATION, message, http_status=400)


async def _request_asr(audio: bytes, content_type: str) -> dict:
    """调用通用 ASR 网关（独立成函数，便于测试打桩）。"""
    settings = get_settings()
    headers = {"Content-Type": content_type}
    if settings.asr_api_key:
        headers["Authorization"] = f"Bearer {settings.asr_api_key}"
    async with httpx.AsyncClient(timeout=settings.asr_timeout_seconds) as client:
        resp = await client.post(settings.asr_endpoint_url, content=audio, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def transcribe(audio: bytes, content_type: str | None = None) -> str:
    """音频字节 → 文字；任何不可用情形都抛业务错误，由前端降级为键盘输入。"""
    settings = get_settings()
    if not settings.asr_enabled:
        raise _degrade("语音转写未开启，请用键盘输入")
    if not audio:
        raise _degrade("没有收到语音内容，请重新录制")
    if len(audio) > settings.asr_max_audio_bytes:
        raise _degrade("这段语音有点长，换段短一点的说吧")

    if settings.asr_provider == "mock":
        # 本地联调占位：不识别真实音频，返回固定提示文本（生产启动校验禁止）
        logger.info("V5 语音转写：mock 提供方返回占位文本，audio_bytes=%d", len(audio))
        return settings.asr_mock_text

    if settings.asr_provider != "http" or not settings.asr_endpoint_url:
        logger.warning(
            "V5 语音转写：提供方未配置（provider=%s），降级为键盘输入", settings.asr_provider
        )
        raise _degrade("语音转写暂时不可用，请用键盘输入")

    ct = (content_type or "").split(";")[0].strip().lower() or "application/octet-stream"
    if ct not in _ALLOWED_CONTENT_TYPES:
        raise _degrade("暂不支持这种音频格式")

    try:
        data = await _request_asr(audio, ct)
    except Exception:
        logger.exception("V5 语音转写：ASR 网关调用失败 audio_bytes=%d", len(audio))
        raise _degrade("语音转写失败，请用键盘输入或再说一次")

    text = (data.get("text") or "").strip()
    if not text:
        raise _degrade("没有听清这段话，换个说法再说一次好吗")
    # 不落原文：日志只记长度
    logger.info("V5 语音转写：成功 text_len=%d", len(text))
    return text
