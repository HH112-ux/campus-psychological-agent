"""主动关怀（V3）请求模型（对齐 API 文档第 8 节）。"""
from __future__ import annotations

from pydantic import BaseModel


class CaringSettingUpdate(BaseModel):
    """关怀开关：true=开启（愿意接收主动问候），false=关闭（用户可随时关闭）。"""

    enabled: bool


class CaringSubscribeRequest(BaseModel):
    """订阅授权回填：小程序 wx.requestSubscribeMessage 用户是否同意（一次性订阅，同意 +1 配额）。"""

    granted: bool
