"""微信服务端接口：code2session 登录换 openid + access_token 管理。

- code2session：用 wx.login 的临时 code 换取 openid。
  真实模式：GET https://api.weixin.qq.com/sns/jscode2session（需要服务端保存 AppSecret）。
  mock 模式（WX_MOCK_LOGIN=true，本地开发默认）：不请求微信，返回固定开发 openid，
  使小程序开发者工具在无 AppSecret 时也能打通登录链路。配好 AppSecret 后置 false 即切真机。
- get_access_token：msgSecCheck 等服务端接口的调用凭证（stable_token），
  内存缓存 + 提前 300s 视为过期 + asyncio.Lock 防并发刷新。
"""
from __future__ import annotations

import asyncio
import logging
import time

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


# ---------- access_token 管理（msgSecCheck 等服务端接口凭证） ----------

_token_cache: dict = {"token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()
# 提前量：距过期不足 300s 即视为过期，避免用到临界 token
_TOKEN_EXPIRE_SKEW_SECONDS = 300


async def _request_stable_token(payload: dict) -> dict:
    """调用 stable_token 接口（独立成函数便于测试打桩）。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(get_settings().wx_stable_token_url, json=payload)
    return resp.json()


def _cached_token(force_refresh: bool) -> str | None:
    if force_refresh:
        return None
    token = _token_cache["token"]
    if token and time.time() < _token_cache["expires_at"]:
        return token
    return None


async def get_access_token(force_refresh: bool = False) -> str:
    """获取微信服务端 access_token，带内存缓存；失败抛 RuntimeError。

    mock 登录模式返回占位 token（mock 下不会真实调用受检接口，仅供链路完整）。
    """
    settings = get_settings()
    if settings.wx_mock_login:
        return "mock_access_token"

    cached = _cached_token(force_refresh)
    if cached:
        return cached

    async with _token_lock:
        # double-check：等待锁期间可能已被其他协程刷新
        cached = _cached_token(force_refresh)
        if cached:
            return cached
        payload = {
            "grant_type": "client_credential",
            "appid": settings.wx_appid,
            "secret": settings.wx_secret,
            "force_refresh": force_refresh,
        }
        data = await _request_stable_token(payload)
        token = data.get("access_token")
        if not token:
            raise RuntimeError(
                f"stable_token 未返回 access_token: errcode={data.get('errcode')} "
                f"errmsg={data.get('errmsg')}"
            )
        expires_in = int(data.get("expires_in", 7200))
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + expires_in - _TOKEN_EXPIRE_SKEW_SECONDS
        return token


def _reset_token_cache() -> None:
    """清空 token 缓存（测试用）。"""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0


# ---------- 订阅消息（V3 主动关怀） ----------

# token 类错误码：access_token 无效/过期，需强制刷新后重试
_TOKEN_ERRCODES = {40001, 40014, 42001}


async def _request_subscribe_send(token: str, payload: dict) -> dict:
    """调用订阅消息发送接口（独立成函数便于测试打桩）。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            get_settings().wx_subscribe_send_url,
            params={"access_token": token},
            json=payload,
        )
    return resp.json()


async def send_subscribe_message(
    openid: str, template_id: str, data: dict, page: str | None = None
) -> dict:
    """发送一次性订阅消息（V3），返回微信原始响应 dict 供调用方判 errcode。

    mock 登录模式返回占位成功响应（不真实发送，仅保证链路完整）；
    token 失效（40001/40014/42001）时强制刷新后重试一次。
    """
    if get_settings().wx_mock_login:
        return {"errcode": 0, "errmsg": "ok(mock)"}

    payload: dict = {"touser": openid, "template_id": template_id, "data": data}
    if page:
        payload["page"] = page

    token = await get_access_token()
    resp = await _request_subscribe_send(token, payload)
    if resp.get("errcode") in _TOKEN_ERRCODES:
        token = await get_access_token(force_refresh=True)
        resp = await _request_subscribe_send(token, payload)
    return resp
