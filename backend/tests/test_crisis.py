"""P1 安全红线测试：本地危机词库两级检测（一票否决，0 高危漏报）。

纯同步逻辑测试，不依赖 MongoDB / event loop，直接对内置词表做判定。
"""
from __future__ import annotations

import asyncio
import types

import pytest

from app.services import crisis
from app.services.crisis import evaluate, normalize
from app.services.crisis_data import LEVEL1_PHRASES, LEVEL2_PHRASES


def detect(text: str, session: dict | None = None) -> crisis.CrisisResult:
    # 必须传原文：豁免/边界判断要读标点，`normalize` 会删掉标点（见 crisis 模块约定）
    return evaluate(
        text,
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
    # —— P5 扩充：暴力他人（一票否决红线）——
    "我想杀人",
    "想报复社会",
    "我想和他同归于尽",
    "弄死他就好了",
    "我想掐死她",
    "我要砍人",
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


# ---------- 复审复现：生理疲惫被判 high ----------
def test_tired_not_crisis():
    """复审实测：命中「累到不想动」+「不想动了」两条重叠词 → 4 分 → high。"""
    r = detect("今天累到不想动了")
    assert r.level == "none"
    assert r.l2_matches == []


@pytest.mark.parametrize(
    "text",
    [
        "今天累到不想动了",
        "累了一天，不想动了",
        "我不想死",          # 否定
        "我没想自杀",
        "我想死你了",        # 寒暄
        "你真是想死我了",
        "我热得要死了",      # 夸张
        "笑死我了",
        "今天累死我了",
        "饿死我了",
    ],
)
def test_everyday_expressions_not_flagged(text):
    assert detect(text).level == "none", f"日常表达误报：{text!r}"


def test_overlapping_l2_terms_counted_once():
    """「没人在乎我」同时命中「没人在乎」与完整词条，只计一次分（mid 而非 high）。"""
    r = detect("没人在乎我")
    assert r.level == "mid"
    assert r.score_added == 2
    assert r.l2_matches == ["没人在乎我"]


# ---------- 第六轮复审 B-1：完整词碰撞只看整词，不看词后接什么 ----------
# 每项：白名单完整词 → 该词在原文里的写法（简体 + 繁体/异体）。
# 新增 `_COLLISION_WORDS` 词条必须在这里补一行，下面的守护测试会直接失败。
COLLISION_FORMS: dict[str, tuple[str, ...]] = {
    "不想活动": ("不想活动", "不想活動"),
    "不想活跃": ("不想活跃", "不想活躍"),
    "不想活蹦乱跳": ("不想活蹦乱跳", "不想活蹦亂跳"),
    "不想活跳跳": ("不想活跳跳",),  # 「活跳跳」是「活蹦乱跳」的简省说法，繁简同形
    "寻死觅活": ("寻死觅活", "尋死覓活"),
}
COLLISION_WORDS = tuple(w for words in crisis._COLLISION_WORDS.values() for w in words)


def test_collision_forms_cover_every_whitelisted_word():
    """新增白名单词而不补写法/繁简映射时，本测试失败，防止繁体覆盖被漏掉。"""
    assert set(COLLISION_FORMS) == set(COLLISION_WORDS)
    for word, forms in COLLISION_FORMS.items():
        assert forms[0] == word
        for form in forms:
            assert form.translate(crisis._COLLISION_T2S) == word, f"{form!r} 未归并到 {word!r}"


@pytest.mark.parametrize("word", COLLISION_WORDS)
@pytest.mark.parametrize("tail", ["只想躺着", "也不想说话", "但我没事", "了"])
def test_complete_collision_word_is_not_crisis(word, tail):
    """完整词后面接任何正常续句都不影响结论（第六轮 8 条误报的根因）。"""
    assert detect(word + tail).level == "none", f"完整词误报：{word + tail!r}"


@pytest.mark.parametrize("word", COLLISION_WORDS)
def test_traditional_collision_word_is_not_crisis(word):
    for form in COLLISION_FORMS[word]:
        assert detect(form + "，只想休息").level == "none", f"繁体完整词误报：{form!r}"


# 词跨度断句集：标点/换行/零宽字符夹在词中间就不是同一个词，必须回落 high
WORD_SPAN_BREAK_CHARS = [
    "。", "！", "？", "；", "，", "、", "：", "…", "—",
    "〜", "～", "·", "・", "「", "」", "（", "）", "“", "”",
    "/", "|", "\n", "\u200b", "\u200c", "\u200d", "\ufeff",
]


@pytest.mark.parametrize("sep", WORD_SPAN_BREAK_CHARS)
def test_word_span_separator_breaks_collocation(sep):
    assert detect(f"我不想活{sep}动").level == "high", f"{sep!r} 被当成了同一个词"


@pytest.mark.parametrize("sep", [" ", "\t", "\u3000", "\u00a0"])
def test_whitespace_inside_word_does_not_break_collocation(sep):
    """空白只是排版，不构成语义边界：完整词被排版写开，仍算完整出现。"""
    assert detect(f"我不想活{sep}动").level == "none", f"{sep!r} 误把完整词拆开"


# 语义邻接（否定/寒暄/夸张）只看标点与换行：空白与零宽字符透明
@pytest.mark.parametrize(
    "text",
    [
        "我不 想死",
        "我不 想自杀",
        "我没有 想死",
        "我没 想过要自杀",
        "我 没 想 过 自 杀",
        "我 不 想 死",
        "我不\u3000想死",
        "我不\u200b想死",
        "我想死 你了",
        "我想死\u200b你了",
        "热得 要死了",
        "热得\u200b要死了",
    ],
)
def test_semantic_adjacency_ignores_whitespace_and_zero_width(text):
    assert detect(text).level == "none", f"排版字符被当成了语义边界：{text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "我不，想死",
        "我不。想死",
        "我想死，你了不了解我",
    ],
)
def test_semantic_adjacency_still_broken_by_punctuation(text):
    assert detect(text).level == "high", f"标点应当构成语义边界：{text!r}"


def test_collision_exemption_does_not_swallow_later_crisis():
    """豁免只作用于那一次命中的完整词，后文真危机按自己的命中判定。"""
    assert detect("我不想活动，但我真的不想活了").level == "high"


def test_real_crisis_continuation_not_exempted():
    """守住第五轮能力：带标点的「不想活 + 后文」仍是真危机，不得退回整词放行。"""
    for text in (
        "我真的不想活，走不动了",
        "不想活，走路都没力气",
        "不想活。动不动就想哭",
        "我不想活，动都不想动",
    ):
        assert detect(text).level == "high", f"真实求助被误放：{text!r}"


# ---------- 收窄后真实危机仍必须命中 ----------
CRISIS_STILL_CAUGHT = [
    ("我想死", "high"),
    ("我不想活了", "high"),
    ("我想自杀", "high"),
    ("我准备跳楼", "high"),
    ("活着没意思", "mid"),
    ("真的撑不下去了", "mid"),
    ("没人在乎我，活着好累", "high"),  # 2 个不重叠的二级词
]


@pytest.mark.parametrize(("text", "level"), CRISIS_STILL_CAUGHT)
def test_real_crisis_still_caught(text, level):
    assert detect(text).level == level, f"收窄后漏报：{text!r}"


def test_db_lexicon_merges_with_builtin(client, db):
    """数据库词库只能追加，不得整体替换内置红线词表。"""
    from app.db.indexes import COLL_CRISIS_LEXICON
    from app.db.mongo import mongo
    from app.services import crisis as crisis_svc

    async def _run():
        await mongo.db[COLL_CRISIS_LEXICON].insert_one(
            {"phrase": "自定义危机词", "level": 1, "enabled": True}
        )
        crisis_svc.refresh_lexicon_cache()
        try:
            l1, _ = await crisis_svc._load_lexicon()
            return l1
        finally:
            await mongo.db[COLL_CRISIS_LEXICON].delete_many({"phrase": "自定义危机词"})
            crisis_svc.refresh_lexicon_cache()

    l1 = client.portal.call(_run)
    assert "想死" in l1, "内置红线词表被数据库词库整体替换了"
    assert "自定义危机词" in l1


# ---------- 缓存失效状态（与宿主机 uptime 无关） ----------
class _FakeCursor:
    """最小 motor cursor 替身：只支持 `async for`。"""

    def __init__(self, docs: list[dict]):
        self._docs = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class _FakeLexiconDb:
    """最小 motor database 替身：只实现 `db[集合].find(...)` 这一条读取路径。"""

    def __init__(self, docs: list[dict]):
        self._docs = docs

    def __getitem__(self, _name: str):
        return types.SimpleNamespace(find=lambda _query: _FakeCursor(self._docs))


def test_refresh_reloads_source_when_monotonic_starts_small(monkeypatch):
    """refresh 后必须回源读 DB，不能被「开机时长 < TTL」挡在缓存里。

    复现生产冷启动：Linux 的 `monotonic` 是开机时长，主机重启后头 60 秒内
    `now - 0.0 < 60` 会让「刚被置失效」的缓存继续被当成新鲜，运营在 DB 追加的
    红线词不生效。这里把 monotonic 固定为 30 秒，结论只取决于缓存状态写法，
    与本机 uptime 无关（旧写法下本用例必红）。
    """
    monkeypatch.setattr(crisis, "time", types.SimpleNamespace(monotonic=lambda: 30.0))
    monkeypatch.setattr(
        crisis,
        "mongo",
        types.SimpleNamespace(
            db=_FakeLexiconDb([{"phrase": "冷启动新增词", "level": 1, "enabled": True}])
        ),
    )

    original = dict(crisis._cache)
    try:
        # 预置一份「刚写入」的旧缓存，只有走缓存才会返回它
        crisis._cache.update(ts=30.0, l1=["缓存旧词"], l2=[])
        crisis.refresh_lexicon_cache()
        assert crisis._cache["ts"] is None, "失效状态应显式置空，不能靠时间戳数值表达"

        l1, _ = asyncio.run(crisis._load_lexicon())
    finally:
        crisis._cache.update(original)

    assert "冷启动新增词" in l1, "refresh 后仍未回源读 DB（走了缓存）"
    assert "缓存旧词" not in l1, "refresh 后仍返回了缓存里的旧词表"
    assert "想死" in l1, "内置红线词表应继续参与并集"
