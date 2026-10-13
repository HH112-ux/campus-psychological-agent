"""P1 测试公共夹具。

- 使用独立测试库 xinyu_test，与开发库 xinyu 隔离；
- 红线危机检测（test_crisis.py）为纯逻辑，不依赖 DB，无 MongoDB 也可运行；
- DB 集成测试通过 client 夹具启动 lifespan，本地未启动 MongoDB 时自动 skip。
"""
from __future__ import annotations

import os

# 必须在导入 app 之前设置环境变量（Settings 首次实例化时读取）
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "xinyu_test")
os.environ.setdefault("WX_MOCK_LOGIN", "true")
os.environ.setdefault("WX_MOCK_OPENID", "mock_test_user")
os.environ.setdefault("JWT_SECRET", "test-secret-please-change-0123456789abcdef")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.indexes import (  # noqa: E402
    COLL_MESSAGES,
    COLL_RISK_EVENTS,
    COLL_SESSIONS,
    COLL_USERS,
)
from app.db.mongo import mongo  # noqa: E402
from app.main import app  # noqa: E402

_CLEAN_COLLS = [COLL_USERS, COLL_SESSIONS, COLL_MESSAGES, COLL_RISK_EVENTS]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        if not mongo.is_connected:
            pytest.skip("本地 MongoDB 未启动，跳过 DB 集成测试")
        yield c


@pytest.fixture()
def db(client):
    """每个测试前清理业务集合（保留危机词库/资源集合，检测器自带兜底）。"""
    for name in _CLEAN_COLLS:
        mongo.db[name].delete_many({})
    from app.core import ratelimit
    from app.services import crisis as crisis_svc
    ratelimit.reset_all()
    crisis_svc.refresh_lexicon_cache()
    yield mongo.db
