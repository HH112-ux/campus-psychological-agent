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
