"""W2 extract_json 单测：围栏 / 杂质 / 截取 / 非对象 / 非法输入。

`app/core/llm_json.py` 是情绪分析与长期记忆抽取共用的解析器（原两份逐字重复的
`_extract_json` 收敛而来）。解析失败在 fail-safe 下是静默的（只「本轮不写」），
故必须有单测锁住容忍边界，避免格式一变两处链路同时失效。
"""
from __future__ import annotations

from app.core.llm_json import extract_json


def test_plain_json_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json_block_with_language():
    raw = '```json\n{"kind": "person", "content": "室友"}\n```'
    assert extract_json(raw) == {"kind": "person", "content": "室友"}


def test_fenced_block_without_language():
    assert extract_json('```\n{"a": 2}\n```') == {"a": 2}


def test_surrounding_noise_is_truncated():
    raw = '这是模型的解释文字 {"a": 3} 后面还有一句尾巴'
    assert extract_json(raw) == {"a": 3}


def test_nested_object_preserved():
    raw = '{"memories": [{"kind": "event", "content": "考研"}]}'
    assert extract_json(raw) == {"memories": [{"kind": "event", "content": "考研"}]}


def test_non_object_values_return_none():
    assert extract_json("[1, 2, 3]") is None
    assert extract_json("42") is None
    assert extract_json('"一段文本"') is None


def test_invalid_json_returns_none():
    assert extract_json("{不是合法 json") is None
    assert extract_json("完全不是 JSON") is None


def test_empty_and_none_return_none():
    assert extract_json("") is None
    assert extract_json("   ") is None
    assert extract_json(None) is None  # 容忍 None（(raw or "") 防空）
