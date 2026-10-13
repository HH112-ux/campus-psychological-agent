"""消息与反馈相关请求模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MessageSend(BaseModel):
    content: str = Field(min_length=1, max_length=2000, description="纯文本，1–2000 字")
    stream: bool = True


class FeedbackRequest(BaseModel):
    rating: Literal["like", "dislike"]
    reason: Literal["no_help", "not_understood", "preachy", "other"] | None = None
