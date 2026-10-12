"""P0 验收测试：/health 返回 200 且结构符合统一响应。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["service"] == "xinyu-backend"
    assert body["data"]["status"] == "ok"
    assert body["data"]["db"] in ("connected", "disconnected")


def test_unknown_route_returns_unified_structure():
    resp = client.get("/api/v1/not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "code" in body and "message" in body and "data" in body


def test_biz_error_uses_unified_structure():
    """验证全局异常处理器输出统一结构（通过一个会触发 BizError 的路径）。"""
    from fastapi import APIRouter

    from app.core.exceptions import BizError
    from app.main import app

    probe = APIRouter()

    @probe.get("/probe-biz-error")
    async def _boom():
        raise BizError(code=5001, message="业务校验失败", http_status=400)

    app.include_router(probe)
    resp = client.get("/probe-biz-error")
    assert resp.status_code == 400
    body = resp.json()
    assert body == {"code": 5001, "message": "业务校验失败", "data": None}
