"""微信 code2session：用 wx.login 的临时 code 换取 openid。

- 真实模式：GET https://api.weixin.qq.com/sns/jscode2session（需要服务端保存 AppSecret）。
- mock 模式（WX_MOCK_LOGIN=true，本地开发默认）：不请求微信，返回固定开发 openid，
  使小程序开发者工具在无 AppSecret 时也能打通登录链路。配好 AppSecret 后置 false 即切真机。
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.core.exceptions import CODE_WX_CODE_INVALID, BizError

logger = logging.getLogger(__name__)


async def code2session(code: str) -> str:
    """用临时 code 换 openid。失败抛 1001。"""
    settings = get_settings()

    if settings.wx_mock_login:
        # 本地开发：固定 openid，模拟同一设备同一用户
        logger.info("wx mock login, code=%s", code[:8])
        return settings.wx_mock_openid

    if not settings.wx_appid or not settings.wx_secret:
        logger.error("微信登录未配置 WX_APPID/WX_SECRET，且未开启 mock")
        raise BizError(CODE_WX_CODE_INVALID, "登录服务未配置，请稍后再试", http_status=401)

    params = {
        "appid": settings.wx_appid,
        "secret": settings.wx_secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(settings.wx_code2session_url, params=params)
        data = resp.json()
    except Exception:
        logger.exception("调用微信 code2session 失败")
        raise BizError(CODE_WX_CODE_INVALID, "微信登录暂时不可用，请稍后再试", http_status=401)

    openid = data.get("openid")
    if not openid:
        logger.warning("code2session 未返回 openid: errcode=%s errmsg=%s",
                       data.get("errcode"), data.get("errmsg"))
        raise BizError(CODE_WX_CODE_INVALID, "登录凭证无效或已过期，请重试", http_status=401)
    return openid
