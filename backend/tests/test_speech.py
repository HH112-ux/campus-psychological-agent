"""V5 语音转写测试：mock 转写 / fail-safe 降级 / 不落原始音频 / 限长 / 网关打桩。"""
from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.core.exceptions import BizError
from app.db.indexes import _INDEX_SPECS
from app.db.mongo import mongo
from app.services import speech
from tests.helpers import auth, login

_ASR_FIELDS = (
    "asr_enabled",
    "asr_provider",
    "asr_endpoint_url",
    "asr_api_key",
    "asr_max_audio_bytes",
    "asr_mock_text",
)


@pytest.fixture()
def asr_settings():
    """保存并恢复 ASR 配置（get_settings 为进程单例，避免污染其他测试）。"""
    s = get_settings()
    saved = {k: getattr(s, k) for k in _ASR_FIELDS}
    yield s
    for k, v in saved.items():
        setattr(s, k, v)


def _post(client, token, content=b"fake-audio-bytes", content_type="audio/mpeg"):
    return client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("voice.mp3", content, content_type)},
        headers=auth(token),
    )


def test_transcribe_mock_returns_placeholder(client, db, asr_settings):
    """mock 提供方（本地联调）返回固定占位文本。"""
    asr_settings.asr_enabled = True
    asr_settings.asr_provider = "mock"
    asr_settings.asr_mock_text = "占位识别结果"
    token = login(client)
    resp = _post(client, token)
    assert resp.status_code == 200
    assert resp.json()["data"]["text"] == "占位识别结果"


def test_transcribe_persists_no_audio(client, db, asr_settings):
    """合规红线：转写不落原始音频、不落任何业务数据（除登录产生的 users）。"""
    asr_settings.asr_provider = "mock"
    token = login(client)
    assert _post(client, token, content=b"raw-audio-marker-xyz").status_code == 200

    async def _counts():
        return {name: await mongo.db[name].count_documents({}) for name in _INDEX_SPECS}

    counts = client.portal.call(_counts)
    assert counts["users"] >= 1
    others = {n: c for n, c in counts.items() if n != "users"}
    assert not any(others.values()), others


def test_transcribe_disabled_degrades(client, db, asr_settings):
    asr_settings.asr_enabled = False
    token = login(client)
    resp = _post(client, token)
    assert resp.status_code == 400
    assert resp.json()["code"] == 5001


def test_transcribe_oversize_degrades(client, db, asr_settings):
    asr_settings.asr_enabled = True
    asr_settings.asr_provider = "mock"
    asr_settings.asr_max_audio_bytes = 4
    token = login(client)
    resp = _post(client, token, content=b"12345678")
    assert resp.status_code == 400
    assert resp.json()["code"] == 5001


def test_transcribe_unsupported_type_degrades(client, db, asr_settings):
    asr_settings.asr_provider = "http"
    asr_settings.asr_endpoint_url = "https://asr.example/asr"
    token = login(client)
    resp = _post(client, token, content_type="text/plain")
    assert resp.status_code == 400
    assert resp.json()["code"] == 5001


def test_transcribe_http_missing_endpoint_degrades(asr_settings):
    """http 提供方未配置网关 → fail-safe 降级（不阻断主链路）。"""
    asr_settings.asr_provider = "http"
    asr_settings.asr_endpoint_url = ""
    with pytest.raises(BizError) as ei:
        asyncio.run(speech.transcribe(b"audio"))
    assert ei.value.code == 5001


def test_transcribe_http_stub_success(asr_settings, monkeypatch):
    """网关返回 text（打桩，不真实联网）；返回体去空白。"""
    asr_settings.asr_provider = "http"
    asr_settings.asr_endpoint_url = "https://asr.example/asr"

    async def fake(audio: bytes, content_type: str) -> dict:
        assert audio == b"hello-audio"
        assert content_type == "audio/mpeg"
        return {"text": "  你好呀  "}

    monkeypatch.setattr(speech, "_request_asr", fake)
    assert asyncio.run(speech.transcribe(b"hello-audio", "audio/mpeg")) == "你好呀"


def test_transcribe_http_empty_text_degrades(asr_settings, monkeypatch):
    asr_settings.asr_provider = "http"
    asr_settings.asr_endpoint_url = "https://asr.example/asr"

    async def fake(audio: bytes, content_type: str) -> dict:
        return {"text": "   "}

    monkeypatch.setattr(speech, "_request_asr", fake)
    with pytest.raises(BizError) as ei:
        asyncio.run(speech.transcribe(b"audio", "audio/mpeg"))
    assert ei.value.code == 5001


def test_transcribe_http_error_degrades(asr_settings, monkeypatch):
    asr_settings.asr_provider = "http"
    asr_settings.asr_endpoint_url = "https://asr.example/asr"

    async def fake(audio: bytes, content_type: str) -> dict:
        raise RuntimeError("gateway 500")

    monkeypatch.setattr(speech, "_request_asr", fake)
    with pytest.raises(BizError) as ei:
        asyncio.run(speech.transcribe(b"audio", "audio/mpeg"))
    assert ei.value.code == 5001


def test_transcribe_requires_auth(client, db):
    resp = client.post(
        "/api/v1/speech/transcribe",
        files={"file": ("voice.mp3", b"x", "audio/mpeg")},
    )
    assert resp.status_code == 401
