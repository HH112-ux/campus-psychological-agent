"""E3 模型路由：启发式分流，零额外 LLM 调用、零额外延迟。

规则（全部满足才走轻量档，否则一律主档）：
- `cost_routing_enabled` 开启；
- 危机级别为 none（危机语境绝不用轻量模型，安全红线）；
- 最近一轮情绪非负面（anxious / depressed / angry 走主档）；
- 内容长度不超过 `cost_routing_light_max_chars`（长文本通常是复杂疏导）。

默认关闭（`cost_routing_enabled=false`），行为与 E2 改造后完全一致。
"""
from __future__ import annotations

from app.config import get_settings
from app.llm import get_chat_provider, get_light_provider
from app.llm.base import LLMProvider

TIER_CHAT = "chat"
TIER_LIGHT = "light"

# 需要主档的情绪（负面/高风险）；calm / ok / other 可走轻量档
_HEAVY_EMOTIONS = frozenset({"anxious", "depressed", "angry"})


def select_tier(
    content: str,
    crisis_level: str = "none",
    latest_emotion: str | None = None,
) -> str:
    """返回本次回复应使用的档位：`chat`（主档）或 `light`（轻量档）。"""
    settings = get_settings()
    if not settings.cost_routing_enabled:
        return TIER_CHAT
    if crisis_level and crisis_level != "none":
        return TIER_CHAT
    if latest_emotion in _HEAVY_EMOTIONS:
        return TIER_CHAT
    if len(content.strip()) > settings.cost_routing_light_max_chars:
        return TIER_CHAT
    return TIER_LIGHT


def provider_for_tier(tier: str) -> LLMProvider:
    """按档位取 provider（轻量档复用 E2 的 light 档，主备映射同样生效）。"""
    return get_light_provider() if tier == TIER_LIGHT else get_chat_provider()


def select_chat_provider(
    content: str,
    crisis_level: str = "none",
    latest_emotion: str | None = None,
) -> tuple[LLMProvider, str]:
    """返回 (provider, tier)，tier 供成本基线记录使用。"""
    tier = select_tier(content, crisis_level, latest_emotion)
    return provider_for_tier(tier), tier
