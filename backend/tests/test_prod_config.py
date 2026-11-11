"""生产配置启动校验（M5 ⑤）：env=prod 时危险/缺失配置 fail-fast，dev 不受影响。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _prod_kwargs(**overrides):
    base = dict(
        env="prod",
        wx_mock_login=False,
        wx_appid="wx_prod_appid",
        wx_secret="wx_prod_secret",
        wx_content_check_enabled=True,
        jwt_secret="p" * 32,
        data_encryption_key="k" * 32,
        mongodb_uri="mongodb://xinyu:strong-pass@mongo:27017/xinyu?authSource=admin",
        zhipu_api_key="zhipu-key",
        asr_provider="http",
        asr_endpoint_url="https://asr.example.cn/asr",
        asr_api_key="asr-key",
    )
    base.update(overrides)
    return base


def test_prod_valid_config_passes():
    s = Settings(**_prod_kwargs())
    assert s.env == "prod"


def test_prod_mock_login_rejected():
    with pytest.raises(ValidationError, match="WX_MOCK_LOGIN"):
        Settings(**_prod_kwargs(wx_mock_login=True))


def test_non_dev_mock_login_rejected():
    """B-2：非 dev 环境一律拒绝 mock 登录（staging 等同样不能让全校共用一个 openid）。"""
    with pytest.raises(ValidationError, match="WX_MOCK_LOGIN"):
        Settings(env="staging", wx_mock_login=True)


def test_prod_missing_appid_secret_rejected():
    with pytest.raises(ValidationError, match="WX_APPID"):
        Settings(**_prod_kwargs(wx_appid="", wx_secret=""))


def test_prod_content_check_disabled_rejected():
    with pytest.raises(ValidationError, match="WX_CONTENT_CHECK_ENABLED"):
        Settings(**_prod_kwargs(wx_content_check_enabled=False))


def test_prod_weak_jwt_secret_rejected():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(**_prod_kwargs(jwt_secret="change-me-in-env"))
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(**_prod_kwargs(jwt_secret="short"))


def test_prod_missing_encryption_key_rejected():
    with pytest.raises(ValidationError, match="DATA_ENCRYPTION_KEY"):
        Settings(**_prod_kwargs(data_encryption_key=""))


def test_prod_mongo_without_credentials_rejected():
    """B1：生产禁止无认证 Mongo 连接串。"""
    with pytest.raises(ValidationError, match="MONGODB_URI"):
        Settings(**_prod_kwargs(mongodb_uri="mongodb://mongo:27017/xinyu"))


def test_prod_missing_zhipu_key_rejected():
    with pytest.raises(ValidationError, match="ZHIPU_API_KEY"):
        Settings(**_prod_kwargs(zhipu_api_key=""))


def test_prod_empty_crisis_phone_rejected(monkeypatch):
    """G3：求助电话不允许为空（空值即无法转介）。"""
    from app.services import crisis_data

    monkeypatch.setattr(
        crisis_data,
        "FALLBACK_RESOURCES",
        {"resources": [{"id": "campus-center", "name": "校心理咨询中心", "phone": ""}]},
    )
    with pytest.raises(ValidationError, match="电话为空"):
        Settings(**_prod_kwargs())


def test_prod_invalid_crisis_phone_rejected(monkeypatch):
    """G3：含非数字字符或长度不符的电话视为非法配置。"""
    from app.services import crisis_data

    for bad in ("0757-ABC", "123", "0757-23456789转"):
        monkeypatch.setattr(
            crisis_data,
            "FALLBACK_RESOURCES",
            {"resources": [{"id": "campus-center", "name": "校心理咨询中心", "phone": bad}]},
        )
        with pytest.raises(ValidationError, match="电话格式非法"):
            Settings(**_prod_kwargs())


def test_campus_center_phone_is_real_number():
    """G3：内置求助资源必须携带校方提供的真实号码，不得回退为占位符。"""
    from app.services.crisis_data import FALLBACK_RESOURCES

    campus = next(
        r for r in FALLBACK_RESOURCES["resources"] if r["id"] == "campus-center"
    )
    assert campus["phone"] == "0757-23456789"


def test_prod_mock_asr_provider_rejected():
    """V5：生产禁止 mock 转写（否则把用户语音都替换成固定文本）。"""
    with pytest.raises(ValidationError, match="ASR_PROVIDER"):
        Settings(**_prod_kwargs(asr_provider="mock"))


def test_prod_http_asr_missing_gateway_rejected():
    with pytest.raises(ValidationError, match="ASR_ENDPOINT_URL"):
        Settings(**_prod_kwargs(asr_endpoint_url="", asr_api_key=""))


def test_prod_asr_disabled_passes():
    """V5：显式关闭语音入口时不要求 ASR 网关配置。"""
    s = Settings(**_prod_kwargs(asr_enabled=False, asr_provider="mock", asr_endpoint_url=""))
    assert s.asr_enabled is False


def test_dev_default_config_unaffected():
    # dev 默认（mock 登录、空密钥）不触发校验
    s = Settings(env="dev")
    assert s.wx_mock_login is True
