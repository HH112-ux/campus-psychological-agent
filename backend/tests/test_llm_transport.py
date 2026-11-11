"""Provider 传输层接线测试（P1）。

现有 33 处测试替身直接打桩 `generate` / `stream`，不覆盖传输实现本身；
本文件用假客户端替换 `build_client`，验证「消息转换 → 调用 → 文本归一化 →
客户端关闭 → 异常包装」这条接线，全程不发网络请求。
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import get_settings
from app.llm.qwen import QwenProvider
from app.llm.zhipu import ZhipuProvider


class _FakeClient:
    """模拟 ChatOpenAI 的最小表面：bind / ainvoke / astream / 异步关闭。"""

    def __init__(self, *, message=None, chunks=(), exc: Exception | None = None) -> None:
        self._message = message
        self._chunks = chunks
        self._exc = exc
        self.bound: dict = {}
        self.messages = None
        self.closed = False

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        if self._exc is not None:
            raise self._exc
        return self._message

    async def astream(self, messages):
        self.messages = messages
        if self._exc is not None:
            raise self._exc
        for chunk in self._chunks:
            yield chunk

    @property
    def root_async_client(self):
        return self

    async def close(self) -> None:
        self.closed = True


def _use_client(monkeypatch, module: str, client: _FakeClient) -> dict:
    captured: dict = {}

    def _fake_build(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr(f"{module}.build_client", _fake_build)
    return captured


def test_zhipu_generate_converts_messages_and_returns_text(monkeypatch):
    fake = _FakeClient(message=AIMessage(content="我在"))
    captured = _use_client(monkeypatch, "app.llm.zhipu", fake)

    text = asyncio.run(
        ZhipuProvider().generate(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
            temperature=0.3,
            max_tokens=50,
        )
    )

    assert text == "我在"
    assert isinstance(fake.messages[0], SystemMessage)
    assert isinstance(fake.messages[1], HumanMessage)
    assert fake.bound == {"temperature": 0.3, "max_tokens": 50}
    assert captured["timeout_seconds"] == get_settings().model_timeout_seconds
    assert fake.closed is True


def test_zhipu_generate_wraps_error_and_closes_client(monkeypatch):
    fake = _FakeClient(exc=ValueError("boom"))
    _use_client(monkeypatch, "app.llm.zhipu", fake)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(ZhipuProvider().generate([{"role": "user", "content": "u"}]))

    assert isinstance(excinfo.value.__cause__, ValueError)
    assert fake.closed is True


def test_zhipu_stream_skips_empty_chunks(monkeypatch):
    fake = _FakeClient(
        chunks=[AIMessage(content="你"), AIMessage(content=""), AIMessage(content="好")]
    )
    _use_client(monkeypatch, "app.llm.zhipu", fake)

    async def _collect():
        return [d async for d in ZhipuProvider().stream([{"role": "user", "content": "u"}])]

    assert asyncio.run(_collect()) == ["你", "好"]
    assert fake.closed is True


def test_qwen_uses_its_own_model_and_base_url(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "qwen_model_chat", "qwen-plus")
    monkeypatch.setattr(settings, "qwen_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1/")
    fake = _FakeClient(message=AIMessage(content="ok"))
    captured = _use_client(monkeypatch, "app.llm.qwen", fake)

    asyncio.run(QwenProvider().generate([{"role": "user", "content": "u"}]))

    assert captured["model"] == "qwen-plus"
    assert captured["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
