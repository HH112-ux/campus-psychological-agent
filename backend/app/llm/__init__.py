"""LLM Provider 工厂（E2 多模型容灾统一出口）。

四个业务调用点（chat × 2、emotion、long_memory）不再自己判断容灾逻辑，
统一走本模块的两个工厂：

- get_chat_provider() —— 主对话档（model_chat / qwen_model_chat）
- get_light_provider() —— 轻量档（model_light / qwen_model_light，情绪分析 & 记忆抽取）

未启用 qwen_enabled 时返回裸 ZhipuProvider，启用且 key 非空时返回
FallbackProvider 包裹 ZhipuProvider + QwenProvider。

这样做的好处：
1. 三处原本拷贝粘贴的 `_make_provider` 合并到一处；
2. 测试 monkeypatch `chat.ZhipuProvider` 依然有效（各模块仍 import 该类名）。
"""
from __future__ import annotations

from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.fallback import FallbackProvider
from app.llm.qwen import QwenProvider
from app.llm.zhipu import ZhipuProvider


def _wrap(primary: ZhipuProvider, backup_model: str) -> LLMProvider:
    settings = get_settings()
    if settings.qwen_enabled and settings.qwen_api_key:
        return FallbackProvider(primary=primary, backup=QwenProvider(model=backup_model))
    return primary


def get_chat_provider() -> LLMProvider:
    """主对话档（glm-4-air ↔ qwen-plus）。"""
    return _wrap(ZhipuProvider(), get_settings().qwen_model_chat)


def get_light_provider() -> LLMProvider:
    """轻量档（glm-4-flash ↔ qwen-turbo）—— 情绪分析 & 长期记忆抽取。"""
    settings = get_settings()
    return _wrap(ZhipuProvider(model=settings.model_light), settings.qwen_model_light)
