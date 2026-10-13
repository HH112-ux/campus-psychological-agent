"""P4 加密工具测试：AES-256-GCM 加解密、日志脱敏。

不依赖 MongoDB，纯逻辑测试。在 dev 模式下（未配置 DATA_ENCRYPTION_KEY）
加密为透明模式（明文存取）；配置密钥后做真正的加解密。
"""
from __future__ import annotations

import base64
import os
import secrets

# 必须在导入 app 模块前设置环境变量
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "xinyu_test")
os.environ.setdefault("JWT_SECRET", "test-secret-please-change-0123456789abcdef")

from app.core import crypto  # noqa: E402


def _reset_crypto():
    """重置加密单例（测试间隔离）。"""
    crypto._aesgcm = None
    crypto._disabled = False


def test_transparent_mode_no_key():
    """未配置密钥时：encrypt 原样返回明文字符串，decrypt 原样返回。"""
    _reset_crypto()
    os.environ["DATA_ENCRYPTION_KEY"] = ""
    from app.config import get_settings
    get_settings().__dict__["data_encryption_key"] = ""

    stored = crypto.encrypt("你好，心屿")
    assert stored == "你好，心屿"
    assert crypto.decrypt(stored) == "你好，心屿"
    assert not crypto.is_enabled()


def test_encrypt_decrypt_roundtrip():
    """配置密钥后：加密返回 dict 结构，解密还原明文。"""
    _reset_crypto()
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    os.environ["DATA_ENCRYPTION_KEY"] = key
    from app.config import get_settings
    get_settings().__dict__["data_encryption_key"] = key

    plaintext = "我最近总是睡不着，很焦虑"
    stored = crypto.encrypt(plaintext)
    assert isinstance(stored, dict)
    assert stored.get("__enc") is True
    assert "iv" in stored
    assert "ct" in stored
    assert "tag" in stored
    # 解密还原
    assert crypto.decrypt(stored) == plaintext
    assert crypto.is_enabled()


def test_decrypt_none_and_string():
    """decrypt 对 None 和明文字符串的兼容处理。"""
    _reset_crypto()
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    os.environ["DATA_ENCRYPTION_KEY"] = key
    from app.config import get_settings
    get_settings().__dict__["data_encryption_key"] = key

    assert crypto.decrypt(None) == ""
    assert crypto.decrypt("明文") == "明文"
    assert crypto.decrypt(123) == "123"


def test_each_encryption_unique_iv():
    """每次加密生成不同 IV（nonce），相同明文密文不同。"""
    _reset_crypto()
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    os.environ["DATA_ENCRYPTION_KEY"] = key
    from app.config import get_settings
    get_settings().__dict__["data_encryption_key"] = key

    s1 = crypto.encrypt("same text")
    s2 = crypto.encrypt("same text")
    assert s1["iv"] != s2["iv"]
    assert s1["ct"] != s2["ct"]
    # 都能正确解密
    assert crypto.decrypt(s1) == "same text"
    assert crypto.decrypt(s2) == "same text"


def test_redact():
    """日志脱敏：不记录原文。"""
    assert crypto.redact("") == "(空)"
    assert crypto.redact("你好") == "(2字)"
    assert crypto.redact("你好世界", max_len=2) == "(4字) 你好…"
    # 默认只返回长度
    assert crypto.redact("一段很长的心理对话内容") == "(11字)"
