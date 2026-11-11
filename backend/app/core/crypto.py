"""对话内容应用层加密（AES-256-GCM）。

开发文档 P4「对话内容应用层加密存储」：
- 明文 content 落库前加密，读取时解密；
- 密钥从环境变量 DATA_ENCRYPTION_KEY 加载，base64url 编码的 32 字节；
- 未配置密钥时（dev 模式）透明存取（content 字段为明文字符串），
  prod 模式下强制要求密钥，否则启动报错；
- 加密后存 { "__enc": true, "key_id": "...", "iv": b64, "ct": b64, "tag": b64 } 结构。

密钥轮换兼容性（P2）：
- 新密文信封带 key_id（默认 v1），历史信封没有该字段也能照常解密；
- 轮换步骤：把新钥写入 DATA_ENCRYPTION_KEY、版本号改为新 id，旧钥写入
  DATA_ENCRYPTION_KEY_PREVIOUS；旧密文先用当前钥解密，InvalidTag 再回退旧钥；
- 历史数据不做批量重写也能继续读；确认全量重写完成后才可移除 previous。
"""
from __future__ import annotations

import base64
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

# 加密标记字段名，落库文档中用此键区分密文与明文
ENC_KEY = "__enc"
_IV_LEN = 12  # GCM 推荐 12 字节 nonce

# 单例：避免每次加解密都生成新的 AESGCM 实例
_aesgcm: AESGCM | None = None
_disabled: bool = False
# 旧钥（轮换兜底）：按配置原文缓存，配置变化时自动重建
_prev_raw: str = ""
_prev_aesgcm: AESGCM | None = None


def _load_key(raw: str, label: str) -> AESGCM:
    """解析 base64url 32 字节密钥，格式错误直接报错（不允许静默降级）。"""
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise RuntimeError(f"{label} 不是合法的 base64url：{exc}") from exc
    if len(key) != 32:
        raise RuntimeError(f"{label} 解码后应为 32 字节，实际 {len(key)} 字节")
    return AESGCM(key)


def _init() -> AESGCM | None:
    """初始化 AESGCM 单例；未配置密钥时返回 None（dev 透明模式）。"""
    global _aesgcm, _disabled
    if _aesgcm is not None or _disabled:
        return _aesgcm

    settings = get_settings()
    raw = settings.data_encryption_key.strip()
    if not raw:
        if settings.env == "prod":
            raise RuntimeError("生产环境必须设置 DATA_ENCRYPTION_KEY（base64url 编码 32 字节）")
        # dev/test 模式：不加密，content 以明文存储
        _disabled = True
        return None

    _aesgcm = _load_key(raw, "DATA_ENCRYPTION_KEY")
    return _aesgcm


def _key_id() -> str:
    """当前写入使用的密钥版本号（用于密文信封审计）。"""
    return get_settings().data_encryption_key_id.strip() or "v1"


def _previous() -> AESGCM | None:
    """轮换期间的旧钥；未配置时返回 None。"""
    global _prev_raw, _prev_aesgcm
    raw = get_settings().data_encryption_key_previous.strip()
    if not raw:
        return None
    if _prev_raw != raw:
        _prev_aesgcm = _load_key(raw, "DATA_ENCRYPTION_KEY_PREVIOUS")
        _prev_raw = raw
    return _prev_aesgcm


def is_enabled() -> bool:
    """当前是否启用加密。"""
    return _init() is not None


def encrypt(plaintext: str) -> str | dict:
    """加密明文。未启用加密时原样返回（明文字符串）。

    返回 dict 结构（含 key_id/iv/ct/tag）或原始明文。
    """
    aes = _init()
    if aes is None:
        return plaintext
    iv = secrets.token_bytes(_IV_LEN)
    ct = aes.encrypt(iv, plaintext.encode("utf-8"), associated_data=None)
    # GCM 的 ct 末尾带 16 字节 tag，cryptography 库合在一起返回
    tag = ct[-16:]
    ciphertext = ct[:-16]
    return {
        ENC_KEY: True,
        "key_id": _key_id(),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def _decrypt_with(aes: AESGCM, iv: bytes, ct: bytes, tag: bytes) -> str:
    return aes.decrypt(iv, ct + tag, associated_data=None).decode("utf-8")


def decrypt(stored: str | dict | None) -> str:
    """解密存储值。未启用加密或值为明文时原样返回。

    - None → 空字符串
    - dict（带 __enc 标记）→ 解密；当前钥失败时回退轮换旧钥
    - str → 明文，原样返回
    """
    if stored is None:
        return ""
    if isinstance(stored, str):
        return stored
    if isinstance(stored, dict) and stored.get(ENC_KEY):
        aes = _init()
        if aes is None:
            # 密钥已撤但 DB 里仍有密文：不应该发生（仅在配置变更时出现）
            return ""
        iv = base64.b64decode(stored["iv"])
        ct = base64.b64decode(stored["ct"])
        tag = base64.b64decode(stored["tag"])
        try:
            return _decrypt_with(aes, iv, ct, tag)
        except InvalidTag:
            previous = _previous()
            if previous is None:
                raise
            return _decrypt_with(previous, iv, ct, tag)
    # 其他类型（数字等）：转字符串
    return str(stored)


def is_encrypted(value: object) -> bool:
    """判断落库值是否为本模块产出的密文结构（用于迁移脚本幂等判断）。"""
    return isinstance(value, dict) and bool(value.get(ENC_KEY))


def encrypt_optional_text(value: str | None) -> str | dict | None:
    """可选文本加密：None/空串原样返回，避免把空值写成密文结构。"""
    if not value:
        return value
    return encrypt(value)


def decrypt_optional_text(value: str | dict | None) -> str | None:
    """可选文本解密：保留 None 语义，不把缺失值变成空串。"""
    if value is None:
        return None
    return decrypt(value)


def redact(content: str, max_len: int = 0) -> str:
    """日志脱敏：只返回长度或截断摘要，不记录原文。

    max_len=0（默认）时只返回 "({n}字)"；max_len>0 时返回前 n 字 + "…"。
    """
    if not content:
        return "(空)"
    n = len(content)
    if max_len <= 0:
        return f"({n}字)"
    if n <= max_len:
        return f"({n}字)"
    return f"({n}字) {content[:max_len]}…"
