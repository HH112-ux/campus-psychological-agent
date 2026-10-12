"""统一响应结构（对齐《API 文档》第 1 节）。

约定：HTTP 状态码只表达传输与鉴权层结果（200/401/429/500），
业务结果一律在响应体 code 中表达，code=0 表示成功。
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "ok") -> dict:
    """成功响应。"""
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str, data: Any = None) -> dict:
    """失败响应体（供异常处理器组装）。"""
    return {"code": code, "message": message, "data": data}


def json_response(status_code: int, payload: dict) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload)


def ok_response(data: Any = None, message: str = "ok", status_code: int = 200) -> JSONResponse:
    return json_response(status_code, ok(data, message))
