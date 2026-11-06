"""H 输出侧合规过滤：诊断结论 / 药物推荐 / 疗效宣称的确定性拦截。"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import chat, compliance
from tests.helpers import auth, create_session, login


@pytest.mark.parametrize(
    "text",
    [
        "你这是典型的抑郁症。",
        "根据你的描述，你患了焦虑症。",
        "你的症状符合双相情感障碍。",
    ],
)
def test_diagnosis_sentences_replaced(text):
    safe, hits = compliance.sanitize(text)
    assert hits == ["diagnosis"]
    assert compliance.SAFE_TEXT["diagnosis"] in safe
    assert "抑郁症" not in safe and "焦虑症" not in safe and "双相" not in safe


@pytest.mark.parametrize(
    "text",
    [
        "建议你吃点舍曲林。",
        "可以服用褪黑素改善睡眠。",
        "如果效果不好可以自行加量。",
    ],
)
def test_medication_sentences_replaced(text):
    safe, hits = compliance.sanitize(text)
    assert hits == ["medication"]
    assert compliance.SAFE_TEXT["medication"] in safe


@pytest.mark.parametrize(
    "text",
    [
        "坚持两周一定能治好。",
        "这个方法可以根治焦虑。",
        "按这个练法一次见效。",
    ],
)
def test_efficacy_sentences_replaced(text):
    safe, hits = compliance.sanitize(text)
    assert hits == ["efficacy"]
    assert compliance.SAFE_TEXT["efficacy"] in safe


@pytest.mark.parametrize(
    "text",
    [
        "我在听，慢慢来，你不用一个人扛着。",
        "如果最近一直睡不好，可以去校心理中心找老师聊聊。",
        "按时吃药、遵医嘱复诊就好。",
    ],
)
def test_safe_sentences_untouched(text):
    safe, hits = compliance.sanitize(text)
    assert safe == text
    assert hits == []


def test_mixed_reply_replaces_only_violating_sentences():
    safe, hits = compliance.sanitize("听到你这么说我很难过。你这是抑郁症。我在陪着你。")
    assert hits == ["diagnosis"]
    assert "我很难过" in safe
    assert "我在陪着你" in safe
    assert "抑郁症" not in safe


def test_output_guard_handles_cross_chunk_sentence():
    guard = compliance.OutputGuard()
    pieces = ["你这是抑郁", "症。", "我在听。"]
    out = "".join([*(guard.feed(p) for p in pieces), guard.flush()])
    assert "抑郁症" not in out
    assert compliance.SAFE_TEXT["diagnosis"] in out
    assert "我在听。" in out
    assert guard.hits == ["diagnosis"]


# ---- 复审实测漏放的四句（原样作为用例）----
@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("你有抑郁症", "diagnosis"),
        ("你可能是抑郁症", "diagnosis"),
        ("你的情况是中度抑郁", "diagnosis"),
        ("可以试试百忧解", "medication"),
    ],
)
def test_recheck_leak_sentences_are_blocked(text, category):
    safe, hits = compliance.sanitize(text)
    assert hits == [category]
    assert safe == compliance.SAFE_TEXT[category]
    assert text not in safe


@pytest.mark.parametrize(
    "text",
    [
        "这听起来像焦虑症。",
        "你疑似抑郁症。",
        "你是轻度焦虑。",
        "你的表现提示重度抑郁。",
    ],
)
def test_diagnosis_inference_and_severity_blocked(text):
    safe, hits = compliance.sanitize(text)
    assert hits == ["diagnosis"]
    assert "抑郁" not in safe and "焦虑症" not in safe


@pytest.mark.parametrize(
    "text",
    [
        "可以试试百忧解。",
        "左洛复和来士普都有人用。",
        "建议服用艾司西酞普兰。",
        "地西泮睡前吃半片。",
    ],
)
def test_medication_brand_and_generic_names_blocked(text):
    safe, hits = compliance.sanitize(text)
    assert hits == ["medication"]
    assert compliance.SAFE_TEXT["medication"] in safe


@pytest.mark.parametrize(
    "text",
    [
        "觉得好些了就可以停药。",
        "你可以自己减量试试。",
        "先停掉舍曲林观察几天。",
    ],
)
def test_stop_or_reduce_medication_advice_blocked(text):
    safe, hits = compliance.sanitize(text)
    assert hits == ["medication"]
    assert compliance.SAFE_TEXT["medication"] in safe


@pytest.mark.parametrize(
    "text",
    [
        "你有点焦虑情绪是很正常的。",
        "考试前你可能会紧张焦虑，这很正常。",
        "不要自行停药，有任何不适及时找医生。",
    ],
)
def test_empathic_normalization_not_blocked(text):
    safe, hits = compliance.sanitize(text)
    assert hits == []
    assert safe == text


def test_output_guard_survives_long_unpunctuated_prefix():
    """复审复现：198 字无标点 + 违规句被拆成两段，旧实现两半都放行。"""
    guard = compliance.OutputGuard()
    pieces = ["a" * 198, "你这", "是抑郁症。", "我在听。"]
    out = "".join([*(guard.feed(p) for p in pieces), guard.flush()])
    assert "抑郁症" not in out
    assert compliance.SAFE_TEXT["diagnosis"] in out
    assert "我在听。" in out
    assert guard.hits == ["diagnosis"]


def test_output_guard_inserts_safe_text_once_per_category():
    """同一条回复内同类违规多次出现时，安全话术只插入一次（非流式与流式一致）。"""
    guard = compliance.OutputGuard()
    pieces = ["你这是抑郁症。", "你可能是焦虑症。", "我在听。"]
    out = "".join([*(guard.feed(p) for p in pieces), guard.flush()])
    assert out.count(compliance.SAFE_TEXT["diagnosis"]) == 1


def test_nonstream_reply_sanitized(client, db, monkeypatch):
    """接入校验：命中合规规则的回复不会原样返回给用户。"""

    async def gen(self, messages, temperature=0.7, max_tokens=1024):
        if "长期记忆抽取器" in messages[0]["content"]:
            return '{"memories": []}'
        return "你这是典型的抑郁症。建议你吃点舍曲林。我在听。"

    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(get_settings(), "emotion_analysis_enabled", False)

    token = login(client)
    sid = create_session(client, token)
    resp = client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": "最近总觉得很难受", "stream": False},
        headers=auth(token),
    )
    text = resp.json()["data"]["assistant_reply"]
    assert "抑郁症" not in text
    assert "舍曲林" not in text
    assert compliance.SAFE_TEXT["diagnosis"] in text
    assert compliance.SAFE_TEXT["medication"] in text
