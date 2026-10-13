"""P1 安全红线测试：本地危机词库两级检测（一票否决，0 高危漏报）。

纯同步逻辑测试，不依赖 MongoDB / event loop，直接对内置词表做判定。
"""
from __future__ import annotations

import pytest

from app.services import crisis
from app.services.crisis import evaluate, normalize
from app.services.crisis_data import LEVEL1_PHRASES, LEVEL2_PHRASES


def detect(text: str, session: dict | None = None) -> crisis.CrisisResult:
    return evaluate(
        normalize(text),
        session or {"crisis_score": 0},
        LEVEL1_PHRASES,
        LEVEL2_PHRASES,
    )


# ---------- 归一化（基础变体覆盖） ----------
def test_normalize_strips_spaces_and_punctuation():
    assert normalize("我 不 想 活 了") == "我不想活了"
    assert normalize("不.想.活！！！") == "不想活"
    assert normalize("BuXiangHuoLe") == "buxianghuole"


# ---------- 一级强信号：100% high ----------
LEVEL1_CASES = [
    "我不想活了",
    "我想自杀",
    "我想去死",
    "我要割腕",
    "我想跳楼",
    "有时候想自残",
    "我准备吃安眠药一了百了",
    "想结束自己的生命",
    "我想了结自己",
    "我 不 想 活 了",       # 字间加空格
    "不.想.活了，好累",      # 字间加标点
    "我zisha算了",          # 拼音
    "wosi",                 # 拼音：我死
    "buxianghuole",         # 拼音：不想活了
    "zican",                # 拼音：自残
    "gewan",                # 拼音：割腕
    "tiaolou",              # 拼音：跳楼
    "紫砂了吧",             # 网络谐音：自杀
]


@pytest.mark.parametrize("text", LEVEL1_CASES)
def test_level1_always_high(text):
    result = detect(text)
    assert result.level == "high", f"高危句漏报：{text!r}（级别 {result.level}）"


# ---------- 二级语境信号：单条 mid ----------
def test_level2_single_is_mid():
    r = detect("最近真的撑不住了，太累了")
    assert r.level == "mid"
    assert r.score_added == 2
    assert r.new_score == 2


def test_level2_other_phrase_mid():
    r = detect("活着好累啊")
    assert r.level == "mid"


# ---------- 二级词同会话累计 ≥4 升 high ----------
def test_level2_accumulate_to_high():
    session = {"crisis_score": 0}
    r1 = detect("最近真的撑不住了", session)
    assert r1.level == "mid"
    session["crisis_score"] = r1.new_score  # 2

    r2 = detect("有时候真想消失，也想要解脱", session)  # 命中 2 个词 +4
    assert r2.level == "high"
    assert r2.new_score >= 4


# ---------- 正常语句不得误报 ----------
SAFE_CASES = [
    "今天天气真好",
    "这游戏真没意思",       # 只有“活着没意思”才是二级词
    "我要去食堂吃饭了",
    "明天有一门期末考试",
    "老师讲的课我有点听不明白",
    "消息怎么突然消失了",   # 日常语境，非“想消失”
]


@pytest.mark.parametrize("text", SAFE_CASES)
def test_safe_text_not_flagged(text):
    r = detect(text)
    assert r.level == "none", f"正常句误报：{text!r}（级别 {r.level}）"
