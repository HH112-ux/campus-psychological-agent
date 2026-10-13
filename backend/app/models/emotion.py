"""情绪识别与打卡相关请求/校验模型（对齐《API 文档》第 7 节、《开发文档》F1/F3）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 打卡情绪五档（F1：平静/还行/低落/焦虑/烦躁）
CheckinMood = Literal["calm", "ok", "low", "anxious", "irritable"]

# 对话情绪六类（F3，与轻量模型 JSON schema 一致）
EmotionType = Literal["calm", "ok", "anxious", "depressed", "angry", "other"]

# 模型风险级别（F4 双保险中由模型侧补全，P3 先落库不触发卡片）
RiskLevel = Literal["none", "low", "mid", "high"]


class CheckinCreate(BaseModel):
    """每日打卡请求（F1：五档情绪 + 可选备注 ≤200 字）。"""

    mood: CheckinMood
    note: str | None = Field(default=None, max_length=200)


class EmotionAnalysis(BaseModel):
    """轻量模型情绪分析输出 schema（开发文档「情绪分析输出 schema」）。

    解析失败或字段越界时按"缺失"处理：不写库、不重试，计一次失败率指标。
    """

    emotion: EmotionType
    intensity: int = Field(ge=1, le=10)
    evidence: str | None = Field(default=None, max_length=50)
    risk_level: RiskLevel = "none"
    strategy_hint: Literal[
        "naming", "grounding", "body_first", "behavior_activation", "referral"
    ] = "naming"
