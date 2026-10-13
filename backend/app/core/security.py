"""JWT 签发与校验（HS256）。

对齐《API 文档》第 2/12 节：
- access token 7 天，refresh token 30 天；
- openid 只存服务端，永不进入令牌、永不下发；
- refresh 采用旋转机制：每次刷新下发新一对令牌，旧 refresh_jti 由调用方在 users 上作废。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import jwt

from app.config import get_settings
from app.core.exceptions import CODE_ACCESS_TOKEN_INVALID, CODE_REFRESH_TOKEN_INVALID, BizError

TYPE_ACCESS = "access"
TYPE_REFRESH = "refresh"


def _now_ts() -> int:
    return int(datetime.now().timestamp())


def _encode(user_id: str, token_type: str, expire_seconds: int) -> tuple[str, str]:
    """签发令牌，返回 (token, jti)。"""
    settings = get_settings()
    if settings.jwt_secret == "change-me-in-env" and settings.env == "prod":
        raise RuntimeError("生产环境必须在环境变量中设置 JWT_SECRET")
    now = _now_ts()
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": now + expire_seconds,
        "jti": jti,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    token, _ = _encode(user_id, TYPE_ACCESS, settings.access_token_expire_seconds)
    return token


def create_token_pair(user_id: str) -> dict:
    """签发一对令牌；refresh_jti 需由调用方写入 users 以支持旋转作废。"""
    settings = get_settings()
    access, _ = _encode(user_id, TYPE_ACCESS, settings.access_token_expire_seconds)
    refresh, refresh_jti = _encode(user_id, TYPE_REFRESH, settings.refresh_token_expire_seconds)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "refresh_jti": refresh_jti,
        "expires_in": settings.access_token_expire_seconds,
    }


def decode_token(token: str, expected_type: str) -> dict:
    """校验并解码令牌；类型不符或过期抛出对应业务错误。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise BizError(
            CODE_REFRESH_TOKEN_INVALID if expected_type == TYPE_REFRESH else CODE_ACCESS_TOKEN_INVALID,
            "登录已过期，请重新登录" if expected_type == TYPE_REFRESH else "access_token 已过期",
            http_status=401,
        )
    except jwt.PyJWTError:
        raise BizError(
            CODE_REFRESH_TOKEN_INVALID if expected_type == TYPE_REFRESH else CODE_ACCESS_TOKEN_INVALID,
            "令牌无效",
            http_status=401,
        )
    if payload.get("type") != expected_type:
        # 用错令牌类型：按对应类型无效处理
        raise BizError(
            CODE_REFRESH_TOKEN_INVALID if expected_type == TYPE_REFRESH else CODE_ACCESS_TOKEN_INVALID,
            "令牌类型不正确",
            http_status=401,
        )
    return payload
