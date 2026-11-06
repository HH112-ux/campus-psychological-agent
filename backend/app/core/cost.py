"""E3 成本基线：按档位累计调用次数与字符数，输出结构化日志。

口径说明：
- 进程内累计，重启归零，多实例各自统计——用于**相对基线**（周环比、档位占比），
  不做精确计费；
- token 不估算成货币：中文场景 1 字符 ≈ 1 token 的粗估偏差较大，故只记字符数，
  由日志系统按周聚合后结合供应商单价换算；
- 每累计 100 次调用输出一条 info，避免逐条刷日志；单次明细走 debug。
"""
from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

_COUNT: dict[str, int] = {}
_PROMPT_CHARS: dict[str, int] = {}
_COMPLETION_CHARS: dict[str, int] = {}

_LOG_EVERY = 100


def _model_for_tier(tier: str) -> str:
    settings = get_settings()
    return settings.model_light if tier == "light" else settings.model_chat


def record_call(tier: str, prompt_chars: int, completion_chars: int) -> None:
    """记录一次模型调用（仅累计，不做 IO；任何异常均不应影响主链路）。"""
    try:
        if not get_settings().cost_tracking_enabled:
            return
        _COUNT[tier] = _COUNT.get(tier, 0) + 1
        _PROMPT_CHARS[tier] = _PROMPT_CHARS.get(tier, 0) + max(0, prompt_chars)
        _COMPLETION_CHARS[tier] = _COMPLETION_CHARS.get(tier, 0) + max(0, completion_chars)

        total = sum(_COUNT.values())
        logger.debug(
            "成本基线 %s(%s) prompt=%d completion=%d",
            tier,
            _model_for_tier(tier),
            prompt_chars,
            completion_chars,
        )
        if total % _LOG_EVERY == 0:
            logger.info("成本基线累计 %d 次 %s", total, snapshot())
    except Exception:  # noqa: BLE001 —— 计量失败绝不能影响对话主链路
        logger.exception("成本计量失败（已忽略）tier=%s", tier)


def snapshot() -> dict[str, dict[str, int]]:
    """当前累计快照：{tier: {calls, prompt_chars, completion_chars}}。"""
    return {
        tier: {
            "calls": _COUNT.get(tier, 0),
            "prompt_chars": _PROMPT_CHARS.get(tier, 0),
            "completion_chars": _COMPLETION_CHARS.get(tier, 0),
        }
        for tier in set(_COUNT) | set(_PROMPT_CHARS) | set(_COMPLETION_CHARS)
    }


def reset() -> None:
    """清空累计（测试与进程内轮转用）。"""
    _COUNT.clear()
    _PROMPT_CHARS.clear()
    _COMPLETION_CHARS.clear()
