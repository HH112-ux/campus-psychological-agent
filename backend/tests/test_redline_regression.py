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


# ---------- 边界判定必须读原文（保留标点），不能读归一化文本 ----------
# 每项：(原文, 归一化后相邻的片段, 期望级别)。
# 中间片段必须在 `normalize(原文)` 里真实相邻——否则这组用例就守不住约定。
RAW_BOUNDARY_CASES = [
    # 逗号吞掉后，后一句的「走」曾被当成「不想活」的完整词豁免依据
    ("我真的不想活，走不动了", "不想活走", "high"),
    # 句号吞掉后，「动不动」曾拼成「不想活动」
    ("不想活。动不动就想哭", "不想活动", "high"),
    # 逗号吞掉后，「动都不想动」曾拼成「不想活动」
    ("我不想活，动都不想动", "不想活动", "high"),
    # 逗号吞掉后，前一句的「不」曾被借给后一句的「我想死」
    ("不，我想死", "不我想", "high"),
    # 逗号吞掉后，前一句的「没有」曾被借给后一句的「想死」
    ("我没有，想死", "没有想死", "high"),
    # 逗号吞掉后，后一句的「你了不了解」曾被当成寒暄「想死你了」
    ("我想死，你了不了解我", "想死你了", "high"),
]


@pytest.mark.parametrize(("text", "adjacent", "expected"), RAW_BOUNDARY_CASES)
def test_crisis_boundary_uses_raw_text_not_normalized(text, adjacent, expected):
    """同一字串在原文被标点分隔、归一化后相邻时，判定必须跟原文语义一致。

    守住 `crisis.py` 的红线约定：模式匹配可以跑归一化文本，但
    「前后文邻接 / 豁免 / 边界」判断必须读保留标点的原文。
    """
    assert adjacent in crisis.normalize(text), "用例前提不成立：归一化后并不相邻"
    result = asyncio.run(crisis.detect_risk(text, {"crisis_score": 0}))
    assert result.level == expected, f"{text!r} 期望 {expected}，实际 {result.level}"


# ---------- 合规侧同一条约定：换行是硬边界，不能先抹掉再判邻接 ----------
# 每项：(原文, `_squash`（去空白/换行）后相邻的片段, 期望类别)。
COMPLIANCE_RAW_BOUNDARY_CASES = [
    # 抹掉换行后，「睡不好」会与下一行的「抑郁症患者」拼成假诊断
    ("你最近是不是睡不好\n抑郁症患者常有这种表现", "睡不好抑郁症", None),
    # 抹掉换行后，问句里的「你…是」会被借给下一行的「抑郁症是什么」
    ("你最近还好吗？\n抑郁症是什么", "吗?抑郁症", None),
    # 线索词带完成体、换行切在线索词与病名之间：按原文语义仍是诊断
    ("你已经确诊了\n抑郁症", "确诊了抑郁症", "diagnosis"),
    # 量词定语跨行：一名 | 抑郁症患者
    ("你是一名\n抑郁症患者", "一名抑郁症", "diagnosis"),
    # 定语「的」跨行：抑郁症的 | 诊断标准
    ("你满足抑郁症的\n诊断标准", "抑郁症的诊断", "diagnosis"),
]


@pytest.mark.parametrize(("text", "adjacent", "expected"), COMPLIANCE_RAW_BOUNDARY_CASES)
def test_compliance_boundary_uses_raw_text_not_squashed(text, adjacent, expected):
    """`_squash` 会让换行两侧「相邻」；判定必须按原文语义，而不是按抹掉换行后的邻接。"""
    assert adjacent in compliance._squash(text), "用例前提不成立：去空白后并不相邻"
    assert compliance.detect(text) == expected
    safe, hits = compliance.sanitize(text)
    if expected is None:
        assert safe == text and hits == []
    else:
        assert hits == [expected] and safe == compliance.SAFE_TEXT[expected]


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


# ---------- 输出侧合规：繁体覆盖（词表新增必须同步补繁体） ----------
# 每个病名/药名的繁体写法；键集合必须与 compliance 的词表完全一致，
# 否则说明词表新增了词而这里没跟上（tests 会直接失败）。
TRAD_DIAGNOSIS_FORMS: dict[str, str] = {
    "抑郁症": "抑鬱症",
    "忧郁症": "憂鬱症",
    "焦虑症": "焦慮症",
    "双相情感障碍": "雙相情感障礙",
    "双相障碍": "雙相障礙",
    "躁郁症": "躁鬱症",
    "强迫症": "強迫症",
    "精神分裂症": "精神分裂症",
    "精神分裂": "精神分裂",
    "创伤后应激障碍": "創傷後應激障礙",
    "PTSD": "PTSD",
    "进食障碍": "進食障礙",
    "人格障碍": "人格障礙",
    "多动症": "多動症",
    "ADHD": "ADHD",
    "自闭症": "自閉症",
    "惊恐障碍": "驚恐障礙",
    "社交恐惧症": "社交恐懼症",
    "社交焦虑障碍": "社交焦慮障礙",
    "躯体化障碍": "軀體化障礙",
    "疑病症": "疑病症",
    "失眠症": "失眠症",
    "抑郁障碍": "抑鬱障礙",
    "焦虑障碍": "焦慮障礙",
}

TRAD_MEDICATION_FORMS: dict[str, str] = {
    "舍曲林": "舍曲林",
    "氟西汀": "氟西汀",
    "帕罗西汀": "帕羅西汀",
    "氟伏沙明": "氟伏沙明",
    "艾司西酞普兰": "艾司西酞普蘭",
    "西酞普兰": "西酞普蘭",
    "文拉法辛": "文拉法辛",
    "度洛西汀": "度洛西汀",
    "米氮平": "米氮平",
    "曲唑酮": "曲唑酮",
    "丁螺环酮": "丁螺環酮",
    "劳拉西泮": "勞拉西泮",
    "阿普唑仑": "阿普唑侖",
    "氯硝西泮": "氯硝西泮",
    "地西泮": "地西泮",
    "奥氮平": "奧氮平",
    "喹硫平": "喹硫平",
    "丙戊酸钠": "丙戊酸鈉",
    "碳酸锂": "碳酸鋰",
    "唑吡坦": "唑吡坦",
    "右佐匹克隆": "右佐匹克隆",
    "佐匹克隆": "佐匹克隆",
    "阿米替林": "阿米替林",
    "多塞平": "多塞平",
    "氯米帕明": "氯米帕明",
    "舍曲林片": "舍曲林片",
    "氟哌啶醇": "氟哌啶醇",
    "坦度螺酮": "坦度螺酮",
    "奥沙西泮": "奧沙西泮",
    "艾司唑仑": "艾司唑侖",
    "氯氮平": "氯氮平",
    "安非他酮": "安非他酮",
    "阿立哌唑": "阿立哌唑",
    "鲁拉西酮": "魯拉西酮",
    "百忧解": "百憂解",
    "左洛复": "左洛復",
    "来士普": "來士普",
    "赛乐特": "賽樂特",
    "怡诺思": "怡諾思",
    "欣百达": "欣百達",
    "瑞美隆": "瑞美隆",
    "思诺思": "思諾思",
    "黛力新": "黛力新",
    "舒乐安定": "舒樂安定",
    "佳静安定": "佳靜安定",
    "安定片": "安定片",
    "阿普唑仑片": "阿普唑侖片",
    "米安色林": "米安色林",
    "曲舍林": "曲舍林",
    "史蒂诺斯": "史蒂諾斯",
    "使蒂诺斯": "使蒂諾斯",
    "赞安诺": "贊安諾",
    "乐复得": "樂復得",
    "SSRI": "SSRI",
    "SNRI": "SNRI",
    "安眠药": "安眠藥",
    "褪黑素": "褪黑素",
    "抗抑郁药": "抗抑鬱藥",
    "抗焦虑药": "抗焦慮藥",
    "镇静剂": "鎮靜劑",
    "抗精神病药": "抗精神病藥",
}


def test_traditional_forms_cover_every_lexicon_term():
    """词表里的每个病名/药名都必须有繁体写法用例（新增词未补繁体即失败）。"""
    assert set(TRAD_DIAGNOSIS_FORMS) == {
        term for term in compliance._DISORDERS.split("|") if term
    }
    assert set(TRAD_MEDICATION_FORMS) == {
        term for term in compliance._DRUGS.split("|") if term
    }


@pytest.mark.parametrize(("simp", "trad"), TRAD_DIAGNOSIS_FORMS.items())
def test_traditional_diagnosis_recognized(simp, trad):
    assert compliance._squash(trad) == simp
    assert compliance.detect(f"你患了{trad}") == "diagnosis"


@pytest.mark.parametrize(("simp", "trad"), TRAD_MEDICATION_FORMS.items())
def test_traditional_medication_recognized(simp, trad):
    assert compliance._squash(trad) == simp
    assert compliance.detect(trad) == "medication"


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


def test_multiline_adjacent_different_categories_keep_newline():
    """S-1：相邻不同类别的命中句各自替换时，中间的换行必须保留。"""
    safe, hits = compliance.sanitize("你有抑郁症\n建议服用舍曲林")

    assert hits == ["diagnosis", "medication"]
    assert safe == (
        f"{compliance.SAFE_TEXT['diagnosis']}\n{compliance.SAFE_TEXT['medication']}"
    )


def test_stream_hold_back_counts_normalized_chars():
    """S-4：保留窗按归一化后长度计算，长空格/逐字换行不能把违规句拆成两半。"""
    guard = compliance.OutputGuard()
    out = guard.feed("疑" + " " * 60 + "似患有创伤后应激障碍")
    out += guard.flush()

    assert "diagnosis" in guard.hits
    assert out == compliance.SAFE_TEXT["diagnosis"]
    assert "疑" not in out


def test_stream_normal_text_prefix_still_released():
    """S-4 不把保留窗放大：纯文本无标点时仍按 48 个归一化字符切。"""
    guard = compliance.OutputGuard()

    assert guard.feed("啊" * 100) == "啊" * 52


@pytest.mark.parametrize(("text", "expected"), COMPLIANCE_CASES)
def test_compliance_never_escapes_when_streamed_char_by_char(text, expected):
    """逐字喂入仍必须命中，证明规则最大匹配跨度 < 保留窗，不会被切点拆开。"""
    if expected is None:
        return
    guard = compliance.OutputGuard()
    out = "".join([*(guard.feed(ch) for ch in text), guard.flush()])
    assert expected in guard.hits, f"逐字流式漏检：{text!r}"
    assert compliance.SAFE_TEXT[expected] in out
