"""业务异常与全局异常处理器（错误码对齐《API 文档》错误码总表）。"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.responses import fail, json_response

logger = logging.getLogger(__name__)

# 错误码常量（对齐 API 文档第 10 节）
CODE_OK = 0
CODE_WX_CODE_INVALID = 1001
CODE_ACCESS_TOKEN_INVALID = 1002
CODE_REFRESH_TOKEN_INVALID = 1003
CODE_NOT_FOUND = 2001
CODE_SESSION_ROUND_LIMIT = 2002
CODE_SESSION_CONCURRENCY_LIMIT = 2003
CODE_CONTENT_INVALID = 2004
CODE_RESOURCE_FORBIDDEN = 2005
CODE_MODEL_DEGRADED = 3001
CODE_MODEL_UNAVAILABLE = 3002
CODE_CRISIS_FLAG = 4001
CODE_BUSINESS_VALIDATION = 5001
CODE_RATE_LIMITED = 9001
CODE_UNKNOWN = 9999


class BizError(Exception):
    """业务异常：携带业务码与用户可见信息。"""

    def __init__(self, code: int, message: str, http_status: int = 400, data: object = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError):
        return json_response(exc.http_status, fail(exc.code, exc.message, exc.data))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # 参数校验失败统一 422 · code=2004（对齐内容/参数非法语义）
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path"))
        msg = f"参数不合法：{loc} {first.get('msg', '')}".strip()
        return json_response(422, fail(CODE_CONTENT_INVALID, msg))

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        # 未捕获的 HTTP 异常按统一结构返回
        return json_response(exc.status_code, fail(exc.status_code * 100, str(exc.detail)))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        # 未知错误：不向客户端暴露内部细节
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return json_response(500, fail(CODE_UNKNOWN, "服务内部错误，请稍后再试"))
