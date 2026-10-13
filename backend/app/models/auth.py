"""认证与用户相关请求模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WxLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128, description="wx.login 临时凭证")
    nickname: str | None = Field(default=None, max_length=30)
    avatar_url: str | None = Field(default=None, max_length=500)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)
