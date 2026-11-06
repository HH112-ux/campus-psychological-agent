"""本地危机词库同步检测（安全红线，不依赖任何模型）。

- 词库从 crisis_lexicon 集合加载（60s TTL 缓存，支持热更新），DB 为空时用内置兜底；
- 归一化后做子串匹配，覆盖“去标点/空格、字间加符号、少量拼音谐音”等基础变体；
- 命中即按危机处理；只有否定词紧邻危机词、或命中词本身是完整寒暄/夸张形态时才豁免
  （白名单式，见 `_is_exempt`），不做「先删疑似安全片段再看剩下」的黑名单剥离；
- 一级命中即 high；二级按命中词计分并累计到会话，≥4 分升 high，否则 mid；
- 触发均写 risk_events（仅记录命中词，不记录对话原文）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from bson import ObjectId

from app.core.crypto import encrypt_optional_text
from app.core.text import normalize
from app.core.timeutil import now_cst, to_iso
from app.db.indexes import (
    COLL_CRISIS_LEXICON,
    COLL_CRISIS_RESOURCES,
    COLL_RISK_EVENTS,
    COLL_SESSIONS,
)
from app.db.mongo import mongo
from app.services import alerting
from app.services.crisis_data import (
    FALLBACK_RESOURCES,
    LEVEL1_PHRASES,
    LEVEL2_HIGH_THRESHOLD,
    LEVEL2_PHRASES,
    LEVEL2_SCORE_PER_HIT,
)

# 词库缓存：{ts, l1, l2}
_CACHE_TTL_SECONDS = 60.0
_cache: dict = {"ts": 0.0, "l1": list(LEVEL1_PHRASES), "l2": list(LEVEL2_PHRASES)}

# ---------- 安全语境豁免（白名单） ----------
# 判定方向：**默认命中即危机**，只有在危机词紧邻位置出现明确的否定/限定词，或
# 命中词本身是完整的寒暄/夸张形态时，才豁免这一次命中。
#
# 为什么不再做「剥离」：第二轮之前是「先把疑似安全的前缀整段删掉，再看剩下」，
# 豁免面是一份黑名单，句式一变（「我想死，你了解吗」）就漏；第三代还出现了一条
# 链路剥离、另一条不剥离的口径分裂。白名单式不删除任何文本，只对「这一次出现」
# 做是否豁免的判断，危机判定与 `contains_crisis_terms` 共用同一个函数。
#
# 距离阈值 `_NEG_WINDOW = 5` 的依据：
# - 否定词必须在危机词前 5 个字以内，且与危机词之间最多只允许 3 个助词/程度词
#   （「没想过要自杀」= 没 + 想过要 3 个；「从来没想过自杀」= 没 + 想过 2 个）；
# - 5 字能覆盖常见的否定表达，又不足以跨过一个分句：归一化会删掉标点，
#   窗口再放宽就会把「不，我想死」的「不」借给后面的「想死」，把真实求助判成否定。
_NEG_WINDOW = 5
_NEG_PREFIX_RE = re.compile(
    r"(?:不|没|没有|别|勿|并非|不是|不会|并不|从未|从没|未曾)"
    r"(?:太|是|再|会|想|要|敢|曾|过|有|去|打算|准备|觉得|那么|怎么){0,3}$"
)
_NEG_TOKEN_RE = re.compile(r"不|没")
# 寒暄：「想死你了 / 想死您了 / 想死我了」，必须带「了」收尾才算完整语气形式；
# 且「了」不能是「了解/了结/了却」这类词的开头（「我想死，你了解吗」是真求助）。
_GREETING_SUFFIX_RE = re.compile(r"(?:你|您|你们|我|我们)了(?!解|结|却|然|断|不起)")
# 夸张：「热得要死了」里的「要死了」由「得」引出
_EXAGGERATION_LEAD = "得"


def _is_exempt(norm: str, start: int, end: int, phrase: str) -> bool:
    """判断某次命中是否属于「安全语境」（白名单，默认不豁免）。"""
    before = norm[max(0, start - _NEG_WINDOW) : start]
    after = norm[end : end + 4]

    if _NEG_PREFIX_RE.search(before) and len(_NEG_TOKEN_RE.findall(before)) < 2:
        # 否定词紧邻危机词；双重否定（「不是不想死」）不豁免
        return True
    if phrase == "想死" and _GREETING_SUFFIX_RE.match(after):
        return True
    if phrase == "要死了" and before.endswith(_EXAGGERATION_LEAD):
        return True
    return False


def _find_hits(norm: str, phrases: list[str]) -> list[str]:
    """返回未被豁免的命中词（同一词任一出现未被豁免即算命中）。"""
    hits: list[str] = []
    for phrase in phrases:
        start = norm.find(phrase)
        while start != -1:
            if not _is_exempt(norm, start, start + len(phrase), phrase):
                hits.append(phrase)
                break
            start = norm.find(phrase, start + 1)
    return hits


def _dedupe_overlapping(hits: list[str]) -> list[str]:
    """重叠词只保留最长的一个：「没人在乎我」同时命中「没人在乎」时只计一次分。

    否则相邻词条会被重复计分（历史上「累到不想动」+「不想动了」=4 分把
    “今天累到不想动了”直接判成 high）。
    """
    kept: list[str] = []
    for phrase in sorted(set(hits), key=len, reverse=True):
        if any(phrase != other and phrase in other for other in kept):
            continue
        kept.append(phrase)
    return sorted(kept)


def refresh_lexicon_cache() -> None:
    """运营热更新后可手动清缓存。"""
    _cache["ts"] = 0.0


async def _load_lexicon() -> tuple[list[str], list[str]]:
    now = time.monotonic()
    if now - _cache["ts"] < _CACHE_TTL_SECONDS:
        return _cache["l1"], _cache["l2"]

    l1: list[str] = []
    l2: list[str] = []
    db = mongo.db
    if db is not None:
        async for doc in db[COLL_CRISIS_LEXICON].find({"enabled": True}):
            phrase = normalize(doc.get("phrase", ""))
            if not phrase:
                continue
            if doc.get("level") == 1:
                l1.append(phrase)
            elif doc.get("level") == 2:
                l2.append(phrase)

    # 数据库词库只做「追加」，与内置词表取并集：
    # 若这里改成替换（l1 or LEVEL1_PHRASES），运营只要在库里写一条词，内置红线
    # 词表就整体失效，危机召回会直接坍塌。
    l1 = sorted(set(LEVEL1_PHRASES) | set(l1))
    l2 = sorted(set(LEVEL2_PHRASES) | set(l2))
    _cache.update(ts=now, l1=l1, l2=l2)
    return l1, l2


@dataclass
class CrisisResult:
    level: str = "none"  # none | mid | high
    l1_matches: list[str] = field(default_factory=list)
    l2_matches: list[str] = field(default_factory=list)
    new_score: int = 0
    score_added: int = 0

    @property
    def hit(self) -> bool:
        return self.level in ("mid", "high")


async def detect_risk(text: str, session: dict) -> CrisisResult:
    """对单条用户消息做本地词库检测（含 DB 热更新词库加载），并结合会话累计分判定。

    全链路只有一处「归一化 + 豁免」：`normalize` 之后直接进入 `evaluate`，
    `evaluate` 内部不再做任何剥离，避免出现「一条链路判 high、另一条判 none」。
    """
    l1, l2 = await _load_lexicon()
    return evaluate(normalize(text), session, l1, l2)


async def contains_crisis_terms(text: str) -> list[str]:
    """确定性复核：返回文本命中的危机词（一级/二级同表），供长期记忆写入前兜底过滤。

    不依赖模型是否遵守提示词：只要抽取结果（或输入）里出现危机词，就整条丢弃。
    与 `detect_risk` 同一口径：`normalize` + `_find_hits`（同一份豁免规则）。
    """
    if not text:
        return []
    l1, l2 = await _load_lexicon()
    return sorted(set(_find_hits(normalize(text), [*l1, *l2])))


def evaluate(norm_text: str, session: dict, l1: list[str], l2: list[str]) -> CrisisResult:
    """纯同步判定：归一化文本 + 会话状态 + 两级词表 → 检测结果（不访问 DB，便于测试）。"""
    current_score = session.get("crisis_score", 0) or 0

    l1_hit = _dedupe_overlapping(_find_hits(norm_text, l1))
    if l1_hit:
        return CrisisResult(level="high", l1_matches=l1_hit, new_score=current_score)

    l2_hit = _dedupe_overlapping(_find_hits(norm_text, l2))
    if l2_hit:
        added = LEVEL2_SCORE_PER_HIT * len(l2_hit)
        new_score = current_score + added
        level = "high" if new_score >= LEVEL2_HIGH_THRESHOLD else "mid"
        return CrisisResult(level=level, l2_matches=l2_hit, new_score=new_score, score_added=added)

    return CrisisResult(level="none", new_score=current_score)


async def record_risk_event(
    user_id: ObjectId,
    session_id: ObjectId,
    level: str,
    matched: list[str],
    trigger: str = "lexicon",
) -> None:
    """写 risk_events（命中词加密存储，读取/导出时解密），留存 ≥12 个月供审计。

    trigger："lexicon"（本地词库命中）或 "model"（模型 risk_level 异步兜底）。
    """
    if mongo.db is None:
        return
    await mongo.db[COLL_RISK_EVENTS].insert_one(
        {
            "user_id": user_id,
            "session_id": session_id,
            "level": level,
            "trigger": trigger,
            "matched": [encrypt_optional_text(x) for x in matched],
            "created_at": now_cst(),
        }
    )
    # M4/M5 ③：高危事件通知值班人（旁路告警，永不抛出；只含 ID 不含命中词）
    if level == "high":
        await alerting.notify_high_risk_event(str(user_id), str(session_id), trigger)


async def handle_model_risk(
    user_id: ObjectId,
    session_id: ObjectId,
    evidence: str | None,
) -> None:
    """P4 危机双保险：模型 risk_level=high 时的异步兜底处理。

    即使本地词库未命中，也：
    1. 记录 risk_events（trigger="model"）供审计；
    2. 升级会话 crisis_high_shown=True，使下一轮展示危机卡片。

    此函数封装"模型判 high 后应该做什么"，避免 emotion.py 直接操作 DB 集合。
    """
    await record_risk_event(
        user_id, session_id, "high",
        matched=[evidence] if evidence else [],
        trigger="model",
    )
    await mongo.db[COLL_SESSIONS].update_one(
        {"_id": session_id},
        {"$set": {"crisis_high_shown": True}},
    )
    # M5 ③：模型兜底命中而词库未命中 → 词库漏报信号（供运营复盘补词）
    await alerting.notify_lexicon_miss(str(user_id), str(session_id))


async def handle_detection(
    text: str,
    session: dict,
) -> tuple[CrisisResult, dict | None, dict]:
    """危机检测 + 会话状态更新 + 风险事件记录（chat.prepare_turn 内聚）。

    返回 (crisis_result, crisis_payload, session_set)：
    - crisis_result：检测结果（含命中级别、命中词、累计分）
    - crisis_payload：前端展示用的危机卡片数据，未命中时为 None
    - session_set：需要 $set 的字段字典（crisis_score / crisis_high_shown / crisis_mid_shown）

    此函数封装"消息进来后危机侧应该做什么"，chat 只管校验+落库+编排。
    """
    crisis = await detect_risk(text, session)
    session_set: dict = {}
    crisis_payload: dict | None = None

    if crisis.score_added:
        session_set["crisis_score"] = crisis.new_score

    if crisis.hit:
        resources = (await get_resources())["resources"]
        if crisis.level == "high":
            show_card = not session.get("crisis_high_shown", False)
            if show_card:
                session_set["crisis_high_shown"] = True
            await record_risk_event(
                session.get("user_id", session.get("_id")),
                session["_id"],
                "high",
                crisis.l1_matches + crisis.l2_matches,
                trigger="lexicon",
            )
        else:
            shown = (
                session.get("crisis_high_shown", False)
                or session.get("crisis_mid_shown", False)
            )
            show_card = not shown
            if show_card:
                session_set["crisis_mid_shown"] = True
            await record_risk_event(
                session.get("user_id", session.get("_id")),
                session["_id"],
                "mid",
                crisis.l2_matches,
                trigger="lexicon",
            )
        crisis_payload = {
            "level": crisis.level,
            "show_card": show_card,
            "resources": resources,
        }

    return crisis, crisis_payload, session_set


async def get_resources() -> dict:
    """求助资源（公开接口）；DB 为权威源，失败用内置兜底副本。"""
    db = mongo.db
    if db is not None:
        doc = await db[COLL_CRISIS_RESOURCES].find_one({"_id": "current"})
        if doc and doc.get("resources"):
            return {
                "version": doc.get("version", 1),
                "updated_at": doc.get("updated_at_iso") or to_iso(doc.get("updated_at", now_cst())),
                "resources": doc["resources"],
            }
    return FALLBACK_RESOURCES
