"""消息对话主链路（开发文档 F2 时序）。

身份校验 → 轮次/长度校验 → 内容安全（msgSecCheck）→ 限流 → 本地危机词库检测
  · high：不调大模型，固定危机话术 + crisis 事件（先于 delta）
  · mid：正常流式生成，结束后下发 crisis 卡片
  · none：正常流式生成
→ user/assistant 各落库 → 窗口近 20 轮记忆 → 智谱流式（超时/异常重试 1 次，仍失败降级）。

对外暴露：
- prepare_turn：在创建 StreamingResponse 之前完成，使校验错误能以普通 JSON 返回；
- reply_nonstream：非流式 JSON 模式（弱网降级路径）；
- stream_events：流式模式，产出 (event, data) 元组，由路由层编码为 SSE 帧。

情绪链路（P3）：回复增量全部下发后、done 事件前异步等待情绪分析（带超时），
成功时流内下发 emotion 事件、回填 assistant 消息 emotion 并写 emotion_records；
分析失败不阻塞（协议允许 emotion 事件缺失）。high 危机路径不触发情绪分析。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from bson import ObjectId

from app.config import get_settings
from app.core.crypto import encrypt
from app.core.exceptions import CODE_CONTENT_INVALID, CODE_SESSION_ROUND_LIMIT, BizError
from app.core.ratelimit import hit_message_rate
from app.core.timeutil import now_cst, to_iso
from app.db.indexes import COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo
from app.db.oid import parse_oid
from app.llm.zhipu import ZhipuProvider
from app.services import alerting, content_security, long_memory, memory
from app.services import emotion as emotion_svc
from app.services.crisis import (
    CrisisResult,
    get_resources,
    handle_detection,
)
from app.services.crisis_data import HIGH_CRISIS_REPLY
from app.services.prompts import build_system_prompt

# 大模型完全不可用时的预设共情话术（F2 降级兜底）
DEGRADED_REPLY = "我还在，刚才走神了，你愿意再说一遍吗"

# 主对话采样温度（温暖、有自然变化）；单次回复 ≤120 字
CHAT_TEMPERATURE = 0.8
CHAT_MAX_TOKENS = 400


@dataclass
class Turn:
    user: dict
    session: dict
    content: str
    user_message_id: str
    crisis: CrisisResult
    crisis_payload: dict | None = None
    risk_level: str = "none"


async def _insert_message(
    session_id, role: str, content: str, risk_level: str = "none", degraded: bool = False
):
    doc = {
        "session_id": session_id,
        "role": role,
        "content": encrypt(content),  # P4：应用层加密存储
        "emotion": None,  # P3 填充
        "risk_level": risk_level,
        "feedback": None,
        "degraded": degraded,
        "created_at": now_cst(),
    }
    result = await mongo.db[COLL_MESSAGES].insert_one(doc)
    return result.inserted_id


async def _pre_turn(
    user: dict, session: dict, raw_content: str
) -> tuple[str, ObjectId]:
    """前置校验 + 限流 + 轮次检查 + 落 user 消息。

    返回 (清洗后的文本, user_message_id)。校验失败直接抛 BizError。
    """
    settings = get_settings()
    text = raw_content.strip()
    if not text or len(text) > settings.message_max_length:
        raise BizError(
            CODE_CONTENT_INVALID, "消息内容不能为空，且不能超过 2000 字", http_status=422
        )

    # 内容安全（M1 / G9，提审要求）：微信 msgSecCheck；命中违规抛 2006，不落库、不计限流
    await content_security.check_text(text, user.get("openid", ""))

    # 应用层限流：30 条/小时/用户
    await hit_message_rate(str(user["_id"]))

    # 轮次上限：50 轮
    if session.get("rounds", 0) >= settings.session_round_limit:
        raise BizError(
            CODE_SESSION_ROUND_LIMIT,
            "这个话题聊得很深了，建议开个新会话",
            http_status=429,
        )

    # 落 user 消息（meta 事件需要其 id）
    user_msg_id = await _insert_message(session["_id"], "user", text, risk_level="none")
    return text, user_msg_id


async def prepare_turn(user: dict, session: dict, raw_content: str) -> Turn:
    """编排：校验 → 危机检测 → 会话更新；返回 Turn。

    前置校验与落 user 消息由 _pre_turn 处理，危机侧由 crisis.handle_detection 处理。
    prepare_turn 只做串联和会话更新的最后一步。
    """
    text, user_msg_id = await _pre_turn(user, session, raw_content)

    # 危机检测 + 风险事件 + 会话状态（crisis 模块内聚）
    crisis, crisis_payload, crisis_session_set = await handle_detection(text, session)
    risk_level = crisis.level if crisis.hit else "none"

    # 更新会话：最近活跃时间 + 首条消息回填标题 + 危机侧字段
    session_set: dict = {"last_msg_at": now_cst()}
    if not session.get("title"):
        session_set["title"] = text[:12]
    session_set.update(crisis_session_set)

    if session_set:
        await mongo.db[COLL_SESSIONS].update_one(
            {"_id": session["_id"]}, {"$set": session_set}
        )

    return Turn(
        user=user,
        session=session,
        content=text,
        user_message_id=str(user_msg_id),
        crisis=crisis,
        crisis_payload=crisis_payload,
        risk_level=risk_level,
    )


async def _finalize(turn: Turn, assistant_text: str, degraded: bool) -> str:
    """落 assistant 消息 + 会话轮次 +1，返回 message_id。"""
    msg_id = await _insert_message(
        turn.session["_id"],
        "assistant",
        assistant_text,
        risk_level=turn.risk_level,
        degraded=degraded,
    )
    await mongo.db[COLL_SESSIONS].update_one(
        {"_id": turn.session["_id"]}, {"$inc": {"rounds": 1}}
    )
    return str(msg_id)


async def _build_messages(turn: Turn) -> list[dict]:
    history = await memory.load_window(turn.session["_id"])
    # 策略层：注入本会话最近一轮情绪分析结果（F3），无记录则用中性占位
    latest_emotion = await emotion_svc.latest_session_emotion(turn.session["_id"])
    # 记忆层（V6）：跨会话长期记忆中与当前话题相关的条目（无关则返回空，克制注入）
    memo_lines = await long_memory.build_injection(turn.user["_id"], turn.content)
    return [
        {
            "role": "system",
            "content": build_system_prompt(latest_emotion=latest_emotion, memories=memo_lines),
        },
        *history,
        {"role": "user", "content": turn.content},
    ]


def _schedule_memory_extraction(turn: Turn) -> None:
    """V6：回复送达后**异步**抽取长期记忆（后台任务，fail-safe，不阻塞回复）。

    - 危机（high）路径不抽取——只做陪伴，不把危机内容长期留存；
    - 抽取在独立任务中执行，任何失败由 long_memory.extract_and_save 内部兜底。
    """
    if not get_settings().long_memory_enabled or turn.crisis.level == "high":
        return
    asyncio.create_task(
        long_memory.extract_and_save(turn.user["_id"], turn.session["_id"], turn.content)
    )


async def _generate_nonstream(turn: Turn) -> tuple[str, bool]:
    """非流式生成，失败重试 1 次；仍失败返回降级话术。"""
    messages = await _build_messages(turn)
    provider = ZhipuProvider()
    for _ in range(2):
        try:
            text = await provider.generate(
                messages, temperature=CHAT_TEMPERATURE, max_tokens=CHAT_MAX_TOKENS
            )
            if text and text.strip():
                return text.strip(), False
        except Exception:  # noqa: BLE001
            continue
    await alerting.notify_llm_degraded("nonstream")
    return DEGRADED_REPLY, True


async def _collect_stream(turn: Turn) -> tuple[list[str], bool]:
    """流式生成并收集全部增量；无内容时重试 1 次，再失败降级；已收到部分则保留。"""
    messages = await _build_messages(turn)
    provider = ZhipuProvider()
    chunks: list[str] = []
    try:
        async for delta in provider.stream(
            messages, temperature=CHAT_TEMPERATURE, max_tokens=CHAT_MAX_TOKENS
        ):
            chunks.append(delta)
    except Exception:
        if chunks:
            # 已有部分内容：保留已收文本，按成功结束
            return chunks, False
        # 无任何内容：重试一次
        try:
            async for delta in provider.stream(
                messages, temperature=CHAT_TEMPERATURE, max_tokens=CHAT_MAX_TOKENS
            ):
                chunks.append(delta)
        except Exception:
            await alerting.notify_llm_degraded("stream")
            return [DEGRADED_REPLY], True
    full = "".join(chunks)
    if not full.strip():
        await alerting.notify_llm_degraded("stream_empty")
        return [DEGRADED_REPLY], True
    return chunks, False


# ---------- 非流式 ----------
async def reply_nonstream(turn: Turn) -> dict:
    if turn.crisis.level == "high":
        assistant_text, degraded = HIGH_CRISIS_REPLY, False
    else:
        assistant_text, degraded = await _generate_nonstream(turn)

    message_id = await _finalize(turn, assistant_text, degraded)
    # V6：后台异步抽取长期记忆（不阻塞返回；high 危机路径内部跳过）
    _schedule_memory_extraction(turn)
    emotion = None
    if turn.crisis.level != "high" and get_settings().emotion_analysis_enabled:
        # 回复落库后做情绪分析：成功回填 assistant 消息并写 emotion_records
        emotion = await emotion_svc.analyze_turn(
            turn.user["_id"],
            turn.session["_id"],
            parse_oid(turn.user_message_id),
            parse_oid(message_id),
            turn.content,
        )
    return {
        "message_id": message_id,
        "assistant_reply": assistant_text,
        "emotion": emotion,
        "risk_level": turn.risk_level,
        "crisis": turn.crisis_payload,
        "degraded": degraded,
        "created_at": to_iso(now_cst()),
    }


# ---------- 流式（SSE 事件） ----------
async def stream_events(turn: Turn) -> AsyncIterator[tuple[str, dict]]:
    yield "meta", {"user_message_id": turn.user_message_id}

    # high：crisis 先于任何 delta，且不调大模型
    if turn.crisis.level == "high":
        yield "crisis", turn.crisis_payload
        yield "delta", {"content": HIGH_CRISIS_REPLY}
        message_id = await _finalize(turn, HIGH_CRISIS_REPLY, False)
        yield "done", {"message_id": message_id, "degraded": False}
        return

    # none / mid：流式生成
    chunks, degraded = await _collect_stream(turn)
    for piece in chunks:
        yield "delta", {"content": piece}
    assistant_text = "".join(chunks)
    message_id = await _finalize(turn, assistant_text, degraded)

    # V6：后台异步抽取长期记忆（不阻塞流；high 危机路径内部跳过）
    _schedule_memory_extraction(turn)

    # mid：流结束后插入求助卡片
    if turn.crisis.level == "mid" and turn.crisis_payload:
        yield "crisis", turn.crisis_payload

    # 情绪分析（P3）：done 之前下发 emotion 事件；失败/超时则协议允许缺失；
    # P5 降级开关关闭时整段跳过（不调模型、不写记录、不发事件）
    emotion = None
    if get_settings().emotion_analysis_enabled:
        emotion = await emotion_svc.analyze_turn(
            turn.user["_id"],
            turn.session["_id"],
            parse_oid(turn.user_message_id),
            parse_oid(message_id),
            turn.content,
        )
    if emotion:
        yield "emotion", emotion
        # P4 危机双保险：模型 risk_level=high 时追加 crisis 事件（异步兜底）
        if emotion.get("risk_level") == "high":
            resources = (await get_resources())["resources"]
            yield "crisis", {
                "level": "high",
                "show_card": True,
                "resources": resources,
                "trigger": "model",
            }

    yield "done", {"message_id": message_id, "degraded": degraded}
