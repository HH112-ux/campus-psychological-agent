"""练习卡片（V4）请求模型（对齐 API 文档第 9 节）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PracticeCompleteRequest(BaseModel):
    """练习完成反馈：可不传时长，缺省用卡片建议时长。"""

    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
