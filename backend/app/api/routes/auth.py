"""认证接口：微信登录、令牌刷新（对齐 API 文档第 4 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.exceptions import CODE_REFRESH_TOKEN_INVALID, BizError
from app.core.responses import ok_response
from app.core.security import TYPE_REFRESH, create_token_pair, decode_token
from app.models.auth import RefreshRequest, WxLoginRequest
from app.services import users as users_svc
from app.services.wechat import code2session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _token_payload(user: dict, tokens: dict) -> dict:
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens["expires_in"],
    }


@router.post("/wx-login")
async def wx_login(body: WxLoginRequest, request: Request):
    # 限流：登录 10 次/分钟/IP（内存固定窗口，单机内测够用）
    from app.core.ratelimit import hit_login_rate
    ip = request.client.host if request.client else "unknown"
    await hit_login_rate(ip)

    openid = await code2session(body.code.strip())
    user, is_new = await users_svc.get_or_create_by_openid(
        openid, body.nickname, body.avatar_url
    )
    tokens = create_token_pair(str(user["_id"]))
    await users_svc.set_refresh_jti(user["_id"], tokens["refresh_jti"])

    data = _token_payload(user, tokens)
    data["is_new"] = is_new
    data["consented"] = bool(user.get("consent_at"))
    return ok_response(data)


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request):
    from app.core.ratelimit import hit_login_rate
    ip = request.client.host if request.client else "unknown"
    await hit_login_rate(ip)

    payload = decode_token(body.refresh_token, TYPE_REFRESH)
    user = await users_svc.get_by_id(payload.get("sub", ""))
    # 旋转校验：仅服务端记录的最新 refresh_jti 有效，旧 token 立即作废
    if not user or user.get("current_refresh_jti") != payload.get("jti"):
        raise BizError(CODE_REFRESH_TOKEN_INVALID, "refresh_token 已失效，请重新登录", http_status=401)

    tokens = create_token_pair(str(user["_id"]))
    await users_svc.set_refresh_jti(user["_id"], tokens["refresh_jti"])
    return ok_response(_token_payload(user, tokens))
