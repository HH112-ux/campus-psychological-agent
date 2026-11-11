"""LangChain 适配构件单测（P0，不发起任何网络请求）。

覆盖：角色映射、未知角色降级、chunk 文本归一化、客户端超时与重试参数。
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.llm.langchain_client import build_client, chunk_text, to_lc_messages


def test_to_lc_messages_maps_known_roles():
    converted = to_lc_messages(
        [
            {"role": "system", "content": "你是陪伴者"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "我在"},
        ]
    )
    assert [type(m) for m in converted] == [SystemMessage, HumanMessage, AIMessage]
    assert [m.content for m in converted] == ["你是陪伴者", "你好", "我在"]


def test_to_lc_messages_unknown_role_falls_back_to_human():
    converted = to_lc_messages([{"role": "tool", "content": "x"}, {"content": "y"}])
    assert all(isinstance(m, HumanMessage) for m in converted)


def test_to_lc_messages_tolerates_empty_content():
    converted = to_lc_messages([{"role": "user", "content": None}])
    assert converted[0].content == ""


def test_chunk_text_returns_string_content():
    assert chunk_text(AIMessage(content="你好")) == "你好"


def test_chunk_text_joins_text_blocks():
    chunk = AIMessage(
        content=[
            {"type": "text", "text": "你"},
            {"type": "image_url", "image_url": {"url": "http://x"}},
            {"type": "text", "text": "好"},
        ]
    )
    assert chunk_text(chunk) == "你好"


def test_chunk_text_empty_content_returns_empty_string():
    assert chunk_text(AIMessage(content=[])) == ""
    assert chunk_text(AIMessage(content="")) == ""


def test_build_client_keeps_timeout_and_disables_sdk_retry():
    client = build_client(
        model="glm-4-air",
        api_key="sk-test",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        timeout_seconds=30.0,
    )
    assert client.model_name == "glm-4-air"
    assert client.openai_api_base == "https://open.bigmodel.cn/api/paas/v4"
    assert client.max_retries == 0
    assert client.request_timeout.read == 30.0
    assert client.request_timeout.connect == 10.0


def test_build_client_accepts_empty_api_key():
    """空 key 不得在构造期抛错，鉴权失败应交由 HTTP 层触发调用方降级。"""
    client = build_client(
        model="glm-4-flash",
        api_key="",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        timeout_seconds=5.0,
    )
    assert client.request_timeout.read == 5.0
