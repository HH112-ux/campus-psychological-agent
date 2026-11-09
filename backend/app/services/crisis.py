"""本地危机词库同步检测（安全红线，不依赖任何模型）。

- 词库从 crisis_lexicon 集合加载（60s TTL 缓存，支持热更新），DB 为空时用内置兜底；
- 归一化后做子串匹配，覆盖“去标点/空格、字间加符号、少量拼音谐音”等基础变体；
- 命中即按危机处理；只有否定词紧邻危机词、或命中词本身是完整寒暄/夸张形态时才豁免
  （白名单式，见 `_is_exempt`），不做「先删疑似安全片段再看剩下」的黑名单剥离；
- **归一化 vs 原文（红线约定，勿破）**：模式匹配跑 `normalize` 后的文本；但凡做
  「前后文邻接 / 豁免 / 边界」判断，一律读**保留标点与换行的原文**（参数名统一带
  `raw_text` / 前缀 `_raw`），归一化下标必须先经 `_normalize_with_offsets` 映射回
  原文再判断。历史三次同形漏报（「想死你」吞句、寒暄前缀剥离、碰撞豁免）都是因为
  在去标点文本上做邻接判断：标点一被删，前一句的否定词、后一句的「走/动」就被借走了；
- 一级命中即 high；二级按命中词计分并累计到会话，≥4 分升 high，否则 mid；
- 触发均写 risk_events（仅记录命中词，不记录对话原文）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from bson import ObjectId

from app.core.crypto import encrypt_optional_text
from app.core.text import KEEP_RE, normalize
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
# `ts` 为 `None` 表示「缓存已失效、下次调用必须回源」，而不是用某个时间戳数值
# （如 0.0）隐式表达失效：`time.monotonic()` 在 Linux 上是开机时长，主机重启后
# 头 60 秒内 `now - 0.0 < 60` 会把「刚被置失效」误判成「仍然新鲜」，运营在 DB
# 追加的红线词要等到 uptime 超过 TTL 才生效。状态用 `None` 显式表达，与 uptime 无关。
_CACHE_TTL_SECONDS = 60.0
_cache: dict = {"ts": None, "l1": list(LEVEL1_PHRASES), "l2": list(LEVEL2_PHRASES)}

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
# 反问/反讽后缀：紧跟在被否定的危机词之后，把否定语义整个翻转
# （「我不想死才怪」= 想死；「我不想死是假的」=「不想死」这件事是假的）。
# 只认**同一分句内、紧接危机词**的后缀：中间出现标点即按语义断开，不在此列
# （「我不想死，才怪」仍按否定豁免）。空白与零宽字符透明，与否定距离同口径。
_REVERSAL_SUFFIX_RE = re.compile(r"^(?:才怪|才不是|是假的|怎么可能|巴不得)")
# ---------- 断句口径（两套，勿混用） ----------
# 原则：**标点表示语义边界；空白与零宽字符只表示排版断行，不代表语义边界。**
# 由此拆成两套，分别服务两类完全不同的问题：
# - `_SEMANTIC_BREAK_RE`：语义邻接判断（否定词距离 / 寒暄完整性 / 夸张形态）。
#   空白与零宽字符透明——「我不 想死」「我不\u200b想死」「我想死 你了」「热得 要死了」
#   仍按同一句处理；只有句读、换行、破折号、引号括号等真正表示语义断开的字符才算边界。
# - `_WORD_SPAN_BREAK_RE`：白名单完整词「在原文里是否连续出现」。
#   标点与换行必然切断；零宽字符不可见、正常中文输入不会产生，夹在词中间只能是刻意
#   插入，无法确认是自然输入的同一个词，按断点保守处理（「我不想活\u200b动」→ high）。
#   空白只是排版空隙（「我不想活 动」= 排版写开的「不想活动」），不算切断整词。
# 共同底线：两套判断都读**原文**，不读归一化文本。
_PUNCT_BREAK_PATTERN = (
    r"。！？!?；;，,、：:…—–‧·・〜～「」『』（）()【】\[\]{}〈〉《》"
    r"“”‘’\"'/|\\\n\r"
)
_SEMANTIC_BREAK_RE = re.compile(f"[{_PUNCT_BREAK_PATTERN}]")
_WORD_SPAN_BREAK_RE = re.compile(f"[{_PUNCT_BREAK_PATTERN}\u200b\u200c\u200d\ufeff]")
# 词内碰撞：命中词只是某个常见词的前缀，不是危机表达。这类不算「句式豁免」，
# 而是子串匹配的边界问题，必须按**完整词**整体匹配：
# 「不想活动 / 不想活跃 / 不想活蹦乱跳」不是「不想活」，「寻死觅活」是成语而非求助。
# 「活跳跳」是「活蹦乱跳」的简省说法（同义），单独收录，不靠单字放行。
# 注意：这里只收「确实以危机词开头」的词；「不想走动」「不想动弹」不含「不想活」，
# 本来就不会命中，无需（也不能）靠单字后缀放行。
_COLLISION_WORDS: dict[str, tuple[str, ...]] = {
    "不想活": (
        "不想活动", "不想活跃", "不想活蹦乱跳", "不想活跳跳",
        # 第九轮复审补齐：同族但此前未收录，旧版本直接判 high（误报）
        "不想活泼", "不想活受罪",
    ),
    "寻死": ("寻死觅活",),
}
# 繁体/异体 → 简体（等长字符映射）：模型输出繁体时「我不想活躍」里只有「躍」
# 与白名单不同字，直接比对会漏。整词比对前先对归一化窗口做一次等长 `translate`，
# 于是新增白名单词时只要用字已在映射中，就自动获得繁体覆盖，不必再维护一份繁体词表。
_COLLISION_T2S = str.maketrans(
    {"動": "动", "躍": "跃", "亂": "乱", "尋": "寻", "覓": "觅", "潑": "泼"}
)


def _normalize_with_offsets(raw_text: str) -> tuple[str, list[int]]:
    """归一化原文，并返回每个归一化字符对应的**原文字符下标**。

    与 `app.core.text.normalize` 同一口径（小写 + 仅保留 `KEEP_RE` 字符），
    额外保留位置映射。模式匹配跑返回的归一化文本，邻接判断一律用
    `offsets` 把下标映射回 `raw_text` 后再做。
    """
    chars: list[str] = []
    offsets: list[int] = []
    for index, ch in enumerate(raw_text):
        for low in ch.lower():
            if KEEP_RE.match(low):
                chars.append(low)
                offsets.append(index)
    return "".join(chars), offsets


def _raw_before(raw_text: str, index: int, limit: int) -> str:
    """取原文中 `index` 之前、同一句内的片段（遇语义边界即停）。

    只按 `_SEMANTIC_BREAK_RE`（标点/换行）截断，空白与零宽字符透明：空格只是排版，
    不该把「我不 想死」的否定词和危机词拆到两段。`limit` 按**内容字符**计数
    （空格不计入），与 `_NEG_WINDOW` 的距离口径一致。
    """
    buf: list[str] = []
    count = 0
    i = index - 1
    while i >= 0 and count < limit:
        ch = raw_text[i]
        if _SEMANTIC_BREAK_RE.match(ch):
            break
        buf.append(ch)
        if KEEP_RE.match(ch.lower()):
            count += 1
        i -= 1
    return "".join(reversed(buf))


def _raw_after(raw_text: str, index: int, limit: int) -> str:
    """取原文中 `index` 之后、同一句内的片段（遇语义边界即停）。

    与 `_raw_before` 同一口径：标点/换行截断，空白与零宽字符透明。跨标点/换行返回
    空串——这正是「后一句的『走』不能给前一句的『不想活』做豁免」的实现方式。
    """
    buf: list[str] = []
    count = 0
    i = index
    while i < len(raw_text) and count < limit:
        ch = raw_text[i]
        if _SEMANTIC_BREAK_RE.match(ch):
            break
        buf.append(ch)
        if KEEP_RE.match(ch.lower()):
            count += 1
        i += 1
    return "".join(buf)


def _is_collocation(
    norm_text: str, raw_text: str, offsets: list[int], start: int, phrase: str
) -> bool:
    """命中词是否只是某个**完整词**的前缀（「不想活动」「寻死觅活」）。

    完整词边界由两步校验，缺一不可：
    1. 整体匹配：归一化文本里命中位置必须完整包含白名单词（`不想活下` ≠ `不想活动`）；
       比对前先做等长繁简归并，繁体「不想活躍」同样视为完整词；
    2. 原文连续：该词在原文里的跨度内不能夹标点/换行/零宽字符（`_WORD_SPAN_BREAK_RE`）；
       空白只是排版空隙，不算切断——「我不想活 动」仍视为完整词「不想活动」。

    只看「词本身是否完整」，**不看词后接什么**：完整词之后的「只想躺着 / 也不想说话 /
    但我没事」都是正常续句，改变不了「这是个完整词」这一事实。第六轮复审的 8 条误报
    就来自这里多要求了「词后必须是句读或语气词」，该约束已去掉。
    """
    for word in _COLLISION_WORDS.get(phrase, ()):
        window = norm_text[start : start + len(word)].translate(_COLLISION_T2S)
        if window != word:
            continue
        raw_word_start = offsets[start]
        raw_word_end = offsets[start + len(word) - 1] + 1
        if _WORD_SPAN_BREAK_RE.search(raw_text[raw_word_start:raw_word_end]):
            continue
        return True
    return False


def _is_exempt(
    norm_text: str,
    raw_text: str,
    offsets: list[int],
    start: int,
    end: int,
    phrase: str,
) -> bool:
    """判断某次命中是否属于「安全语境」（白名单，默认不豁免）。

    红线约定：`start/end` 是归一化下标，只用于定位；**这里每一个判断都读
    `raw_text`**，并且先用 `offsets` 映射回原文再取前后文，避免把标点两侧的
    文字误当成紧邻（「不想活，走不动了」的逗号、「不，我想死」的逗号）。
    """
    raw_start = offsets[start]
    raw_end = offsets[end - 1] + 1
    before_raw = normalize(_raw_before(raw_text, raw_start, _NEG_WINDOW))
    after_raw = normalize(_raw_after(raw_text, raw_end, 6))

    if _NEG_PREFIX_RE.search(before_raw) and len(_NEG_TOKEN_RE.findall(before_raw)) < 2:
        # 否定词与危机词必须在同一分句内紧邻；双重否定（「不是不想死」）不豁免。
        # 但反问/反讽后缀会把否定语义翻转（「不想死才怪」= 想死），此时不豁免；
        # 后缀必须紧跟危机词、且中间无标点，真实的否定表达（「我不想死，
        # 我还没活够」）句内没有这类后缀，仍按否定豁免。
        if _REVERSAL_SUFFIX_RE.match(after_raw):
            return False
        return True
    if phrase == "想死" and _GREETING_SUFFIX_RE.match(after_raw):
        return True
    if phrase == "要死了" and before_raw.endswith(_EXAGGERATION_LEAD):
        return True
    if _is_collocation(norm_text, raw_text, offsets, start, phrase):
        return True          # 完整词前缀（不想活动 / 寻死觅活）
    return False


def _find_hits(raw_text: str, phrases: list[str]) -> list[str]:
    """返回未被豁免的命中词（同一词任一出现未被豁免即算命中）。

    `raw_text` 必须是原文；归一化只在本函数内部发生，并把位置映射传给
    `_is_exempt`，保证豁免判断用的是原文边界。
    """
    norm_text, offsets = _normalize_with_offsets(raw_text)
    hits: list[str] = []
    for phrase in phrases:
        start = norm_text.find(phrase)
        while start != -1:
            end = start + len(phrase)
            if not _is_exempt(norm_text, raw_text, offsets, start, end, phrase):
                hits.append(phrase)
                break
            start = norm_text.find(phrase, start + 1)
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
    """运营热更新后可手动清缓存：把 `ts` 置 `None`，下一次加载必然回源。"""
    _cache["ts"] = None


async def _load_lexicon() -> tuple[list[str], list[str]]:
    now = time.monotonic()
    last = _cache["ts"]
    # 只有「确实写入过时间戳」且未超过 TTL 才算新鲜；`None` 单独表达失效状态，
    # 不参与数值比较，因此不受 monotonic 冷启动（开机不足 60 秒）影响。
    if last is not None and now - last < _CACHE_TTL_SECONDS:
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

    全链路只有一处「归一化 + 豁免」：原文进入 `evaluate`，内部统一归一化并保留
    位置映射，豁免判断再用原文边界，避免出现「一条链路判 high、另一条判 none」。
    """
    l1, l2 = await _load_lexicon()
    return evaluate(text, session, l1, l2)


async def contains_crisis_terms(text: str) -> list[str]:
    """确定性复核：返回文本命中的危机词（一级/二级同表），供长期记忆写入前兜底过滤。

    不依赖模型是否遵守提示词：只要抽取结果（或输入）里出现危机词，就整条丢弃。
    与 `detect_risk` 同一口径：原文直接进 `_find_hits`（同一份豁免规则与边界判断）。
    """
    if not text:
        return []
    l1, l2 = await _load_lexicon()
    return sorted(set(_find_hits(text, [*l1, *l2])))


def evaluate(raw_text: str, session: dict, l1: list[str], l2: list[str]) -> CrisisResult:
    """纯同步判定：**原文** + 会话状态 + 两级词表 → 检测结果（不访问 DB，便于测试）。

    参数必须传用户原文（保留标点/换行），不要传 `normalize` 的结果：
    方法内部自己归一化并保留位置映射，否则豁免判断会失去标点边界。
    """
    current_score = session.get("crisis_score", 0) or 0

    l1_hit = _dedupe_overlapping(_find_hits(raw_text, l1))
    if l1_hit:
        return CrisisResult(level="high", l1_matches=l1_hit, new_score=current_score)

    l2_hit = _dedupe_overlapping(_find_hits(raw_text, l2))
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
