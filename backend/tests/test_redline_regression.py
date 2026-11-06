"""红线回归（第一道门）：危机判定 / 长期记忆兜底 / 输出侧合规。

语料见 `tests/redline_corpus.py`（两轮复审的全部样本，正反俱全）。
任何人改动危机词表、否定剥离、合规规则或长期记忆兜底，先跑本文件：

    pytest -q tests/test_redline_regression.py

任一失败都意味着触碰安全红线，不允许带着提交。
"""
from __future__ import annotations

import asyncio

import pytest
from bson import ObjectId

from app.db.indexes import COLL_RISK_EVENTS
from app.services import alerting, compliance, crisis
from app.services.crisis_data import LEVEL1_PHRASES, LEVEL2_PHRASES
from tests.redline_corpus import (
    COMPLIANCE_CASES,
    COMPLIANCE_STREAM_CASES,
    CRISIS_CASES,
    MEMORY_CASES,
)


@pytest.fixture(autouse=True)
def _builtin_lexicon(monkeypatch):
    """语料测试只依赖内置红线词表，不连 DB，保证任何环境结果一致。"""

    async def _fake_load():
        return list(LEVEL1_PHRASES), list(LEVEL2_PHRASES)

    monkeypatch.setattr(crisis, "_load_lexicon", _fake_load)


# ---------- 危机判定 ----------
@pytest.mark.parametrize(("text", "expected"), CRISIS_CASES)
def test_crisis_corpus(text, expected):
    result = asyncio.run(crisis.detect_risk(text, {"crisis_score": 0}))
    assert result.level == expected, f"{text!r} 期望 {expected}，实际 {result.level}"


# ---------- 危机求助句式必须触发高危告警 ----------
HELP_SEEKING = [text for text, level in CRISIS_CASES[:6]]


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def find_one(self, *args, **kwargs):
        return None


class _FakeDB:
    def __init__(self):
        self.collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


class _FakeMongo:
    def __init__(self):
        self.db = _FakeDB()


@pytest.mark.parametrize("text", HELP_SEEKING)
def test_help_seeking_crisis_triggers_alert(monkeypatch, text):
    calls: list[tuple[str, str, str]] = []

    async def fake_notify(user_id, session_id, trigger):
        calls.append((user_id, session_id, trigger))

    monkeypatch.setattr(alerting, "notify_high_risk_event", fake_notify)
    monkeypatch.setattr(crisis, "mongo", _FakeMongo())

    user_id, session_id = ObjectId(), ObjectId()
    result, payload, _ = asyncio.run(
        crisis.handle_detection(
            text, {"_id": session_id, "user_id": user_id, "crisis_score": 0}
        )
    )

    assert result.level == "high"
    assert payload is not None and payload["level"] == "high" and payload["show_card"]
    assert calls == [(str(user_id), str(session_id), "lexicon")]
    assert crisis.mongo.db[COLL_RISK_EVENTS].docs[0]["level"] == "high"


# ---------- 长期记忆确定性兜底 ----------
@pytest.mark.parametrize(("text", "expected"), MEMORY_CASES)
def test_memory_fallback_corpus(text, expected):
    assert bool(asyncio.run(crisis.contains_crisis_terms(text))) is expected, text


# ---------- 输出侧合规：非流式 ----------
@pytest.mark.parametrize(("text", "expected"), COMPLIANCE_CASES)
def test_compliance_corpus(text, expected):
    assert compliance.detect(text) == expected, f"{text!r} 期望 {expected}"
    safe, hits = compliance.sanitize(text)
    if expected is None:
        assert safe == text and hits == []
    else:
        assert hits == [expected]
        assert safe == compliance.SAFE_TEXT[expected]


# ---------- 输出侧合规：流式分段 ----------
@pytest.mark.parametrize(("pieces", "expected"), COMPLIANCE_STREAM_CASES)
def test_compliance_stream_corpus(pieces, expected):
    guard = compliance.OutputGuard()
    out = "".join([*(guard.feed(p) for p in pieces), guard.flush()])
    assert expected in guard.hits
    assert compliance.SAFE_TEXT[expected] in out


# ---------- 输出侧合规：多行局部替换（爆炸半径） ----------
def test_multiline_only_hit_sentence_replaced():
    """多行回复中只有一句违规时，其余正常句子与换行原样保留。"""
    text = (
        "先做三次深呼吸。\n"
        "你可以试试每天散步十分钟。\n"
        "你就是抑郁症。\n"
        "如果持续两周，可以找老师聊聊。"
    )
    safe, hits = compliance.sanitize(text)

    assert hits == ["diagnosis"]
    assert safe == (
        "先做三次深呼吸。\n"
        "你可以试试每天散步十分钟。\n"
        f"{compliance.SAFE_TEXT['diagnosis']}\n"
        "如果持续两周，可以找老师聊聊。"
    )


def test_multiline_cross_newline_word_still_blocked():
    """跨换行断词的违规句仍被拦下，且只替换参与命中的那几行。"""
    text = "你今天怎么样？\n你有抑\n郁症。我在听。\n要聊聊吗？"
    safe, hits = compliance.sanitize(text)

    assert hits == ["diagnosis"]
    assert safe.startswith("你今天怎么样？\n")
    assert "你有抑" not in safe and "郁症" not in safe
    assert compliance.SAFE_TEXT["diagnosis"] in safe
    assert "我在听。" in safe
    assert safe.endswith("\n要聊聊吗？")


def test_multiline_consecutive_violations_all_blocked():
    """同一段连续多句违规时不漏拦，三类话术都替换、正常收尾保留。"""
    text = "你就是抑郁症。\n建议服用舍曲林。\n坚持吃药就会好起来。\n我在听。"
    safe, hits = compliance.sanitize(text)

    assert hits == ["diagnosis", "medication", "efficacy"]
    for category in hits:
        assert compliance.SAFE_TEXT[category] in safe
    assert "抑郁症" not in safe
    assert "舍曲林" not in safe
    assert "好起来" not in safe
    assert safe.endswith("\n我在听。")


def test_multiline_normal_text_unchanged():
    """无违规的多行文本（含空行）必须逐字保留。"""
    text = "先做三次深呼吸。\n你可以试试每天散步十分钟。\n\n如果持续两周，可以找老师聊聊。"
    assert compliance.sanitize(text) == (text, [])


def test_multiline_complete_sentence_not_joined():
    """上一行已是完整句时不跨行拼接，避免把下一行科普句误判成诊断结论。"""
    text = "你最近是不是压力很大？\n抑郁症需要专业医生诊断，别自己吓自己。"
    assert compliance.sanitize(text) == (text, [])


def test_multiline_context_across_line_still_blocked():
    """诊断语境被换行拆到两行时仍被拦；只替换真正命中的那一句。"""
    text = "你的情况\n可能是抑郁症，建议尽快就医。"
    safe, hits = compliance.sanitize(text)

    assert hits == ["diagnosis"]
    assert safe == f"你的情况\n{compliance.SAFE_TEXT['diagnosis']}"


def test_multiline_third_party_not_borrowed():
    """H-1：跨行不借上一行的人称/判断词，第三方叙述与科普原样保留。"""
    for text in (
        "你最近是不是睡不好\n抑郁症患者常有这种表现",
        "我有个朋友得了\n抑郁症，现在好多了",
    ):
        assert compliance.sanitize(text) == (text, [])


def test_multiline_split_word_still_blocked():
    """H-1/H-2：术语被换行切断仍拦，按字换行不留孤立残字。"""
    safe, hits = compliance.sanitize("你有抑\n郁症")
    assert hits == ["diagnosis"]
    assert safe == compliance.SAFE_TEXT["diagnosis"]

    safe, hits = compliance.sanitize("你\n有\n抑\n郁\n症")
    assert hits == ["diagnosis"]
    assert safe == compliance.SAFE_TEXT["diagnosis"]


@pytest.mark.parametrize(("text", "expected"), COMPLIANCE_CASES)
def test_compliance_never_escapes_when_streamed_char_by_char(text, expected):
    """逐字喂入仍必须命中，证明规则最大匹配跨度 < 保留窗，不会被切点拆开。"""
    if expected is None:
        return
    guard = compliance.OutputGuard()
    out = "".join([*(guard.feed(ch) for ch in text), guard.flush()])
    assert expected in guard.hits, f"逐字流式漏检：{text!r}"
    assert compliance.SAFE_TEXT[expected] in out
