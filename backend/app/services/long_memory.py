"""长期记忆服务（V6）。

在 20 轮窗口记忆之外，增加**跨会话长期记忆**：从用户消息中抽取关键
**人物 / 事件 / 偏好 / 情绪诱因**，加密落库；后续回复按**相关性**克制注入。

设计与边界（对齐 roadmap §5.3 V6）：
- 抽取链路与情绪分析同源（轻量模型 + 严格 JSON 解析），失败 fail-safe：
  任何异常/解析失败一律「本轮不写」，绝不阻断对话主链路；
- **记忆内容同样加密**（AES-256-GCM，复用 core.crypto），日志只记条数，不含原文；
- **允许用户查看 / 删除**（PIPL 行权，与 M3 删除机制共用：已在隐私导出与物理删除纳入）；
- **注入克制**：按与当前消息的字符重合度选「相关记忆」，条数与总字数双上限，
  仅在与当前话题相关时带出，不做逐条罗列（避免喧宾夺主）；
- 涉及自伤/自杀等危机信息一律不抽取为记忆（只做陪伴，不把危机内容长期留存）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Iterable

from bson import ObjectId

from app.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.timeutil import now_cst, to_iso
from app.db.indexes import COLL_MEMORIES
from app.db.mongo import mongo
from app.llm.zhipu import ZhipuProvider

logger = logging.getLogger(__name__)

# 记忆类别：人物 / 事件 / 偏好 / 情绪诱因
MEMORY_KINDS = ("person", "event", "preference", "trigger")

# 抽取参数（temperature 0.2 固定，保证可复现）
EXTRACT_TEMPERATURE = 0.2
EXTRACT_MAX_TOKENS = 300
MAX_ITEMS_PER_TURN = 3  # 单轮最多写入条数
MAX_CONTENT_CHARS = 40  # 单条记忆正文上限

# 类别中文别名 → 枚举（容忍模型输出中文，降低解析失败率）
_KIND_ALIASES = {
    "person": "person",
    "人物": "person",
    "event": "event",
    "事件": "event",
    "preference": "preference",
    "偏好": "preference",
    "习惯": "preference",
    "trigger": "trigger",
    "诱因": "trigger",
    "情绪诱因": "trigger",
}

# 归一化保留：小写字母、数字、CJK 统一汉字（其余标点/空白剔除）
_KEEP_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]")

_EXTRACT_SYSTEM_INSTRUCTION = (
    "你是校园心理陪伴产品「心屿」的长期记忆抽取器。请从用户这句话里，"
    "抽取值得长期记住、且以后聊天能用上的稳定信息，只输出一个 JSON 对象，"
    "不要输出任何其他文字：\n"
    '{"memories": [{"kind": "四选一", "content": "不超过30字的口语化事实"}]}\n'
    "kind 可选：person（人物，如室友/辅导员/家人）、event（事件，如考研/实习/比赛）、"
    "preference（偏好，如喜欢的放松方式/作息）、trigger（情绪诱因，如某件事/某个场景让人长期紧绷）。\n"
    "规则：\n"
    "- 只记**稳定的、可持续复用**的事实，不记一次性的当下情绪（如「今天好难过」不记）。\n"
    "- 涉及自伤、自杀等危机信息一律不要抽取。\n"
    "- 没有可记的内容时输出 {\"memories\": []}。\n"
    "- 最多 3 条；content 用第三人称陈述事实，不要复述原句、不要给建议或评价。"
)

# 失败率监控（进程内计数；与情绪分析同口径）
_fail_count = 0
_total_count = 0


def _extract_json(raw: str) -> dict | None:
    """从模型输出中提取 JSON 对象（容忍 markdown 代码块与前后杂质）。"""
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_memory_json(raw: str) -> list[dict]:
    """解析抽取输出：归一化类别、裁剪长度、批内去重、条数封顶；非法即丢弃。"""
    obj = _extract_json(raw)
    if not obj:
        return []
    raw_items = obj.get("memories")
    if not isinstance(raw_items, list):
        return []

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        kind = _KIND_ALIASES.get(str(raw_item.get("kind", "")).strip().lower())
        if kind is None:
            continue
        content = str(raw_item.get("content", "")).strip()
        content = " ".join(content.split())[:MAX_CONTENT_CHARS]
        if not content:
            continue
        key = (kind, content)
        if key in seen:
            continue
        seen.add(key)
        items.append({"kind": kind, "content": content})
        if len(items) >= MAX_ITEMS_PER_TURN:
            break
    return items


def _content_hash(kind: str, content: str) -> str:
    """去重键：类别 + 归一化正文的 SHA-256（避免同一事实反复入库）。"""
    norm = "".join(ch.lower() for ch in content if _KEEP_RE.match(ch))
    return hashlib.sha256(f"{kind}\x00{norm}".encode()).hexdigest()


def _record_failure() -> None:
    global _fail_count, _total_count
    _total_count += 1
    _fail_count += 1
    if _total_count >= 20 and _fail_count / _total_count > 0.05:
        logger.warning(
            "长期记忆抽取失败率 %.0f%%（%d/%d），触发告警阈值（>5%%）",
            _fail_count / _total_count * 100,
            _fail_count,
            _total_count,
        )
        _fail_count = 0
        _total_count = 0


def _record_success() -> None:
    global _total_count
    _total_count += 1


async def save_memories(
    user_id: ObjectId, session_id: ObjectId, items: Iterable[dict]
) -> int:
    """加密落库并去重（同一 (类别, 正文) 已存在则只刷新更新时间）。返回写入/刷新条数。"""
    if mongo.db is None:
        return 0
    now = now_cst()
    saved = 0
    for item in items:
        kind, content = item["kind"], item["content"]
        await mongo.db[COLL_MEMORIES].update_one(
            {"user_id": user_id, "content_hash": _content_hash(kind, content)},
            {
                "$set": {
                    "kind": kind,
                    "content": encrypt(content),  # 记忆内容同样加密
                    "source_session_id": session_id,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        saved += 1
    if saved:
        await _enforce_cap(user_id)
    return saved


async def _enforce_cap(user_id: ObjectId) -> None:
    """单用户条数上限：超出时删除最旧的（最小化留存）。"""
    cap = get_settings().long_memory_max_items
    if cap <= 0:
        return
    total = await mongo.db[COLL_MEMORIES].count_documents({"user_id": user_id})
    if total <= cap:
        return
    excess = total - cap
    cursor = (
        mongo.db[COLL_MEMORIES]
        .find({"user_id": user_id}, {"_id": 1})
        .sort("updated_at", 1)
        .limit(excess)
    )
    ids = [doc["_id"] async for doc in cursor]
    if ids:
        await mongo.db[COLL_MEMORIES].delete_many({"_id": {"$in": ids}})


async def extract_and_save(
    user_id: ObjectId, session_id: ObjectId, user_text: str
) -> int:
    """抽取并保存长期记忆（fail-safe：任何失败返回 0，不阻断主链路）。

    由对话主链路在回复落库后**异步**触发（后台任务），不阻塞用户看到回复。
    """
    settings = get_settings()
    if not settings.long_memory_enabled or mongo.db is None:
        return 0
    text = user_text.strip()
    if not text:
        return 0

    provider = ZhipuProvider(model=settings.model_light)
    try:
        raw = await asyncio.wait_for(
            provider.generate(
                [
                    {"role": "system", "content": _EXTRACT_SYSTEM_INSTRUCTION},
                    {"role": "user", "content": text},
                ],
                temperature=EXTRACT_TEMPERATURE,
                max_tokens=EXTRACT_MAX_TOKENS,
            ),
            timeout=settings.long_memory_extract_timeout_seconds,
        )
    except Exception:  # noqa: BLE001 —— 超时/网络/模型异常统一按失败处理
        _record_failure()
        logger.info("长期记忆抽取失败（调用异常），跳过本轮 session=%s", session_id)
        return 0

    items = parse_memory_json(raw)
    _record_success()
    if not items:
        return 0
    try:
        saved = await save_memories(user_id, session_id, items)
    except Exception:  # noqa: BLE001 —— 落库失败同样 fail-safe，不影响对话
        logger.exception("长期记忆落库失败，跳过本轮 session=%s", session_id)
        return 0
    # 隐私红线：日志只记条数，不含记忆原文
    logger.info("长期记忆抽取成功：写入/刷新 %d 条 session=%s", saved, session_id)
    return saved


# ---------- 查看 / 删除（PIPL 行权） ----------
async def list_memories(user_id: ObjectId) -> dict:
    """返回用户的长期记忆（解密后可读），按最近更新倒序。"""
    if mongo.db is None:
        return {"memories": [], "total": 0}
    cursor = (
        mongo.db[COLL_MEMORIES]
        .find({"user_id": user_id})
        .sort("updated_at", -1)
    )
    items = [
        {
            "memory_id": str(doc["_id"]),
            "kind": doc.get("kind"),
            "content": decrypt(doc.get("content")),
            "created_at": to_iso(doc.get("created_at")) if doc.get("created_at") else None,
            "updated_at": to_iso(doc.get("updated_at")) if doc.get("updated_at") else None,
        }
        async for doc in cursor
    ]
    return {"memories": items, "total": len(items)}


async def delete_memory(user_id: ObjectId, memory_id: ObjectId) -> bool:
    """删除单条记忆；不存在返回 False（路由侧转 2001）。"""
    if mongo.db is None:
        return False
    result = await mongo.db[COLL_MEMORIES].delete_one(
        {"_id": memory_id, "user_id": user_id}
    )
    return bool(result.deleted_count)


async def clear_memories(user_id: ObjectId) -> int:
    """清空该用户全部长期记忆，返回删除条数。"""
    if mongo.db is None:
        return 0
    result = await mongo.db[COLL_MEMORIES].delete_many({"user_id": user_id})
    return int(result.deleted_count)


# ---------- 克制注入 ----------
def _terms(text: str) -> set[str]:
    """归一化后取字符 2-gram 集合（CJK 无分词，2-gram 近似词重合度）。"""
    norm = "".join(ch.lower() for ch in text if _KEEP_RE.match(ch))
    if not norm:
        return set()
    if len(norm) == 1:
        return {norm}
    return {norm[i : i + 2] for i in range(len(norm) - 1)}


async def build_injection(user_id: ObjectId, current_text: str) -> list[str]:
    """选出与当前消息**相关**的记忆正文（克制：条数 + 总字数双上限）。

    仅保留与当前消息有字符重合（重合度 > 0）的记忆，按重合度、再按最近更新排序；
    无相关记忆时返回空列表（不强行带入）。任何异常返回空，绝不阻断对话。
    """
    settings = get_settings()
    if not settings.long_memory_enabled or mongo.db is None:
        return []
    try:
        cursor = (
            mongo.db[COLL_MEMORIES]
            .find({"user_id": user_id})
            .sort("updated_at", -1)
        )
        docs = [doc async for doc in cursor]
    except Exception:  # noqa: BLE001 —— 记忆读取失败不影响对话
        logger.exception("长期记忆读取失败，本轮不注入 user=%s", user_id)
        return []

    query = _terms(current_text)
    scored: list[tuple[int, dict]] = []
    for doc in docs:
        overlap = len(query & _terms(decrypt(doc.get("content"))))
        if overlap > 0:
            scored.append((overlap, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    lines: list[str] = []
    used = 0
    for _, doc in scored:
        content = decrypt(doc.get("content")).strip()
        if not content:
            continue
        if len(lines) >= settings.long_memory_inject_max_items:
            break
        if used + len(content) > settings.long_memory_inject_max_chars:
            break
        lines.append(content)
        used += len(content)
    return lines
