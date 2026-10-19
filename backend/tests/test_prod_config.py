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


def test_prod_missing_zhipu_key_rejected():
    with pytest.raises(ValidationError, match="ZHIPU_API_KEY"):
        Settings(**_prod_kwargs(zhipu_api_key=""))


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
