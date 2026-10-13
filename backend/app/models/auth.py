"""认证与用户相关请求模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WxLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128, description="wx.login 临时凭证")
    nickname: str | None = Field(default=None, max_length=30)
    avatar_url: str | None = Field(default=None, max_length=500)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ConsentRequest(BaseModel):
    agree: bool = Field(description="是否同意隐私政策")
    policy_version: str | None = Field(default=None, description="隐私政策版本号")


class EraseRequest(BaseModel):
    confirm_text: str = Field(description='必须等于"删除"，防止误触')

