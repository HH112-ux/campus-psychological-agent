"""本地危机词库同步检测（安全红线，不依赖任何模型）。

- 词库从 crisis_lexicon 集合加载（60s TTL 缓存，支持热更新），DB 为空时用内置兜底；
- 归一化后做子串匹配，覆盖“去标点/空格、字间加符号、少量拼音谐音”等基础变体；
- 一级命中即 high；二级按命中词计分并累计到会话，≥4 分升 high，否则 mid；
- 触发均写 risk_events（仅记录命中词，不记录对话原文）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from bson import ObjectId

from app.core.timeutil import now_cst, to_iso
from app.db.indexes import (
    COLL_CRISIS_LEXICON,
    COLL_CRISIS_RESOURCES,
    COLL_RISK_EVENTS,
    COLL_SESSIONS,
)
from app.db.mongo import mongo
from app.services.crisis_data import (
    FALLBACK_RESOURCES,
    LEVEL1_PHRASES,
    LEVEL2_HIGH_THRESHOLD,
    LEVEL2_PHRASES,
    LEVEL2_SCORE_PER_HIT,
)

# 保留：小写字母、数字、CJK 统一汉字；其余（空格/标点/符号/emoji）一律剔除
_KEEP_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]")

# 词库缓存：{ts, l1, l2}
_CACHE_TTL_SECONDS = 60.0
_cache: dict = {"ts": 0.0, "l1": list(LEVEL1_PHRASES), "l2": list(LEVEL2_PHRASES)}


def normalize(text: str) -> str:
    """归一化：小写 + 剔除空白与所有标点符号，使“不 想.活了”等同“不想活了”。"""
    return "".join(ch for ch in text.lower() if _KEEP_RE.match(ch))


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

    # DB 未配置（未跑种子）时用内置兜底，保证红线始终可用
    l1 = sorted(set(l1 or LEVEL1_PHRASES))
    l2 = sorted(set(l2 or LEVEL2_PHRASES))
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
    """对单条用户消息做本地词库检测（含 DB 热更新词库加载），并结合会话累计分判定。"""
    l1, l2 = await _load_lexicon()
    return evaluate(normalize(text), session, l1, l2)


def evaluate(norm_text: str, session: dict, l1: list[str], l2: list[str]) -> CrisisResult:
    """纯同步判定：归一化文本 + 会话状态 + 两级词表 → 检测结果（不访问 DB，便于测试）。"""
    current_score = session.get("crisis_score", 0) or 0

    l1_hit = sorted({p for p in l1 if p in norm_text})
    if l1_hit:
        return CrisisResult(level="high", l1_matches=l1_hit, new_score=current_score)

    l2_hit = sorted({p for p in l2 if p in norm_text})
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
    """写 risk_events（仅命中词，不写对话原文），留存 ≥12 个月供审计。

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
            "matched": matched,
            "created_at": now_cst(),
        }
    )


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
