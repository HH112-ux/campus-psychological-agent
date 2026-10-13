"""会话相关请求模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=20, description="可省略，缺省取首条消息前 12 字")


class SessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=20)
