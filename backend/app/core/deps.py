"""FastAPI 公共依赖：当前登录用户解析。"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import CODE_ACCESS_TOKEN_INVALID, BizError
from app.core.security import TYPE_ACCESS, decode_token
from app.services import users as users_svc

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """解析 Bearer access_token，返回用户文档；失败统一 401/1002。"""
    if creds is None or not creds.credentials:
        raise BizError(CODE_ACCESS_TOKEN_INVALID, "缺少 access_token", http_status=401)
    payload = decode_token(creds.credentials, TYPE_ACCESS)
    user = await users_svc.get_by_id(payload.get("sub", ""))
    if not user:
        raise BizError(CODE_ACCESS_TOKEN_INVALID, "用户不存在或已注销", http_status=401)
    return user
