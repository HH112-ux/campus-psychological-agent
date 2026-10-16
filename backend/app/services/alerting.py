"""监控告警 MVP（M5 ③ / M4 值班人通知链路）。

三处敏感触发点：
1. 高危风险事件（record_risk_event level==high）→ notify_high_risk_event；
2. 模型兜底命中而词库未命中（handle_model_risk）→ notify_lexicon_miss（词库漏报信号，供运营补词）；
3. LLM 重试后仍失败走降级话术 → notify_llm_degraded。

设计原则：
- 永不抛出：告警是旁路，任何异常只记日志，绝不能影响对话主链路；
- 冷却去抖：同一 key 在 alert_cooldown_seconds 内只发一次 webhook（日志始终记录）；
- 隐私红线：告警内容只含 ID / 级别 / 触发源 / 时间，不含命中词与对话原文；
- 触达通道：企业微信群机器人 webhook（未配置 URL 时仅记日志，便于 dev 观察）。
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_SECONDS = 3.0

# 冷却表：key → 上次 webhook 发送时间（monotonic）
_last_sent: dict[str, float] = {}


def reset_cooldowns() -> None:
    """清空冷却表（测试钩子）。"""
    _last_sent.clear()


async def send_alert(key: str, title: str, lines: list[str]) -> None:
    """发送一条告警：始终记 warning 日志；冷却内跳过 webhook；异常只记日志不抛出。"""
    settings = get_settings()
    content = "\n".join([f"【心屿告警】{title}", *lines])
    logger.warning("alert[%s] %s", key, content.replace("\n", " | "))

    if not settings.alert_enabled or not settings.alert_webhook_url:
        return

    now = time.monotonic()
    last = _last_sent.get(key)
    if last is not None and now - last < settings.alert_cooldown_seconds:
        logger.info("alert[%s] 冷却中，跳过 webhook 发送", key)
        return

    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                settings.alert_webhook_url,
                json={"msgtype": "text", "text": {"content": content}},
            )
            resp.raise_for_status()
        _last_sent[key] = now
    except Exception:
        logger.exception("alert[%s] webhook 发送失败（不影响主链路）", key)


async def notify_high_risk_event(user_id: str, session_id: str, trigger: str) -> None:
    """高危风险事件 → 通知值班人（M4 链路）。冷却 key 按会话：同一会话不重复轰炸。"""
    await send_alert(
        key=f"high_risk:{session_id}",
        title="高危风险信号",
        lines=[
            f"用户: {user_id}",
            f"会话: {session_id}",
            f"触发源: {trigger}",
            "请值班人按 crisis-response-sop 跟进（隐私边界：不得查看对话原文，仅核实干预动作）。",
        ],
    )


async def notify_lexicon_miss(user_id: str, session_id: str) -> None:
    """模型判 high 而本地词库未命中 → 词库漏报信号（供运营复盘补词）。"""
    await send_alert(
        key="lexicon_miss",
        title="词库漏报信号",
        lines=[
            f"用户: {user_id}",
            f"会话: {session_id}",
            "模型兜底判 high 但词库未命中，请运营复盘是否补充词库。",
        ],
    )


async def notify_llm_degraded(path: str) -> None:
    """LLM 重试后仍失败、返回降级话术 → 模型服务异常信号。"""
    await send_alert(
        key="llm_degraded",
        title="LLM 调用降级",
        lines=[
            f"路径: {path}",
            "重试后仍失败，已返回降级话术；请检查模型服务与网络。",
        ],
    )
