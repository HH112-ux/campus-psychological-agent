"""情绪分析链路（开发文档 F3 / AI 能力「情绪分析输出 schema」）。

职责：回复送达后（流内 done 前 / 非流式返回前）调用轻量模型，
对"本轮用户消息 + 前两轮上下文"输出结构化 JSON，校验通过后：
1. 回填 assistant 消息的 emotion 字段（会话详情可读，供"日志页数据与对话内容抽查一致"）；
2. 写入 emotion_records（含 evidence，供日志页展示"为什么这么判"）。

失败语义（F3 边界与异常）：分析超时、模型异常或 JSON 解析失败 → 本轮不写
情绪记录（宁可缺失不写错误数据），不重试，失败计数入监控；连续失败率 > 5% 告警。

说明：为满足《API 文档》SSE 协议中 "emotion 事件出现在 done 之前" 的契约，
分析在流内 delta 全部下发后、done 事件前等待完成（带超时）；回复增量本身
不被阻塞，满足"情绪分析永远不阻塞回复"。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence

from bson import ObjectId

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.timeutil import now_cst
from app.db.indexes import COLL_EMOTION_RECORDS, COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo
from app.llm.zhipu import ZhipuProvider
from app.models.emotion import EmotionAnalysis

logger = logging.getLogger(__name__)

# 轻量模型分析参数（temperature 0.2 固定，保证可复现）
EMOTION_TEMPERATURE = 0.2
EMOTION_MAX_TOKENS = 200

# 中文情绪词 → 枚举映射（容忍模型输出中文，降低解析失败率）
_EMOTION_ALIASES = {
    "平静": "calm",
    "还行": "ok",
    "还好": "ok",
    "焦虑": "anxious",
    "紧张": "anxious",
    "担心": "anxious",
    "低落": "depressed",
    "抑郁": "depressed",
    "沮丧": "depressed",
    "难过": "depressed",
    "悲伤": "depressed",
    "愤怒": "angry",
    "生气": "angry",
    "烦躁": "angry",
    "其他": "other",
    "其它": "other",
}

_RISK_ALIASES = {"none": "none", "low": "low", "mid": "mid", "high": "high", "中": "mid", "高": "high"}

_VALID_EMOTIONS = ("calm", "ok", "anxious", "depressed", "angry", "other")
_VALID_HINTS = ("naming", "grounding", "body_first", "behavior_activation", "referral")


def _resolve_emotion(raw: str) -> str | None:
    """归一化情绪值：中文别名 / 枚举校验；容忍模型把枚举语法抄进值（如 "anxious|depressed"），
    取管道分隔中第一个合法项（模型通常把主导情绪放在最前）。"""
    for piece in raw.split("|"):
        piece = piece.strip()
        resolved = _EMOTION_ALIASES.get(piece, piece)
        if resolved in _VALID_EMOTIONS:
            return resolved
    return None

# 失败率监控（进程内计数；P4 起接入正式监控指标）
_fail_count = 0
_total_count = 0


def _extract_json(raw: str) -> dict | None:
    """从模型输出中提取 JSON 对象（容忍 markdown 代码块与前后杂质）。"""
    text = raw.strip()
    # 去掉 ```json ... ``` 围栏
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1).strip()
    # 直接整体解析
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # 截取第一个 { 到最后一个 } 再解析
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_emotion_json(raw: str) -> EmotionAnalysis | None:
    """严格解析 + 轻量归一化；任何字段非法即返回 None（按缺失处理）。"""
    obj = _extract_json(raw)
    if not obj:
        return None

    emotion_raw = str(obj.get("emotion", "")).strip().lower()
    emotion = _resolve_emotion(emotion_raw)
    if emotion is None:
        return None

    try:
        intensity = int(obj.get("intensity"))
    except (TypeError, ValueError):
        return None
    if not 1 <= intensity <= 10:
        return None

    evidence = obj.get("evidence")
    evidence = str(evidence).strip()[:50] if evidence else None

    risk_raw = str(obj.get("risk_level", "none")).strip().lower()
    risk_level = _RISK_ALIASES.get(risk_raw, "none")

    hint_raw = str(obj.get("strategy_hint", "naming")).strip().lower()
    strategy_hint = "naming"
    for piece in hint_raw.split("|"):
        piece = piece.strip()
        if piece in _VALID_HINTS:
            strategy_hint = piece
            break

    return EmotionAnalysis(
        emotion=emotion,
        intensity=intensity,
        evidence=evidence,
        risk_level=risk_level,
        strategy_hint=strategy_hint,
    )


_EMOTION_SYSTEM_INSTRUCTION = (
    "你是校园心理陪伴产品「心屿」的情绪识别器。请阅读用户最近几轮对话，"
    "识别当前这条用户消息的情绪，只输出一个 JSON 对象，不要输出任何其他文字：\n"
    '{"emotion": "六选一", "intensity": 1到10的整数, '
    '"evidence": "不超过50字的原文摘录", '
    '"risk_level": "四选一", "strategy_hint": "五选一"}\n'
    "字段取值（每次只能从对应集合中选择**一个**值，禁止并列多个或使用竖线分隔）：\n"
    "emotion 可选：calm（平静/良好）、ok（还行）、anxious（焦虑/紧张/担心）、"
    "depressed（低落/抑郁/难过）、angry（愤怒/烦躁/生气）、other（其他）；\n"
    "risk_level 可选：none、low、mid、high；\n"
    "strategy_hint 可选：naming（命名情绪）、grounding（接地练习）、body_first（身体优先）、"
    "behavior_activation（行为激活）、referral（转介建议）。\n"
    "类别判定细则（V2）：\n"
    "- 焦虑：紧张、担心、坐立不安、害怕糟糕后果（如考试/面试/等待结果）；"
    "「迷茫、无望、难熬、失去兴趣、无力」属低落而非焦虑。\n"
    "- 低落：难过、无力、没意思、无望、持续低气压；「未来一片迷茫、这一天好难熬、"
    "对什么都提不起兴趣」均为低落。\n"
    "- 平静：明确积极、放松、满意、安心、成就感；中性偏可、只是还行 → ok。\n"
    "- 愤怒：生气、烦躁、不公、被冒犯、想发泄。\n"
    "对抗表达识别（V2）：\n"
    "- 「我没事/我真的没事/我开心得很/我可太优秀了」等自我安慰反话或反讽，"
    "按其真实情绪判定（通常为低落/难过）。\n"
    "- 引用歌词、转述他人（他说/朋友说/歌词唱的）且非表达自己情绪时，"
    "视为无明显情绪，输出 calm 或 other。\n"
    "规则：evidence 必须引用用户原文；无明显情绪时 emotion=other、intensity=3、risk_level=none。"
)


async def _build_analysis_messages(
    session_id: ObjectId, current_content: str, skip_ids: Sequence[ObjectId]
) -> list[dict]:
    """组装分析输入：系统指令 + 前两轮上下文（最多 4 条）+ 本轮用户消息。"""
    cursor = (
        mongo.db[COLL_MESSAGES]
        .find(
            {
                "session_id": session_id,
                "_id": {"$nin": list(skip_ids)},
                "role": {"$in": ["user", "assistant"]},
            }
        )
        .sort("created_at", -1)
        .limit(4)
    )
    history = [m async for m in cursor]
    history.reverse()
    messages = [{"role": "system", "content": _EMOTION_SYSTEM_INSTRUCTION}]
    messages.extend({"role": m["role"], "content": decrypt(m.get("content"))} for m in history)
    messages.append({"role": "user", "content": current_content})
    return messages


def _record_failure() -> None:
    global _fail_count, _total_count
    _total_count += 1
    _fail_count += 1
    if _total_count >= 20 and _fail_count / _total_count > 0.05:
        logger.warning(
            "情绪分析失败率 %.0f%%（%d/%d），触发告警阈值（>5%%）",
            _fail_count / _total_count * 100,
            _fail_count,
            _total_count,
        )
        _fail_count = 0
        _total_count = 0


def _record_success() -> None:
    global _total_count
    _total_count += 1


async def analyze_turn(
    user_id: ObjectId,
    session_id: ObjectId,
    user_message_id: ObjectId,
    assistant_message_id: ObjectId,
    current_content: str,
) -> dict | None:
    """对当前轮做情绪分析，成功时回填 assistant 消息并写 emotion_records。

    返回供 emotion 事件/非流式响应使用的 {type, intensity, evidence}；
    任何失败（超时/异常/解析失败）返回 None，不写库不重试。
    """
    settings = get_settings()
    messages = await _build_analysis_messages(
        session_id, current_content, skip_ids=[user_message_id, assistant_message_id]
    )
    provider = ZhipuProvider(model=settings.model_light)
    try:
        raw = await asyncio.wait_for(
            provider.generate(
                messages,
                temperature=EMOTION_TEMPERATURE,
                max_tokens=EMOTION_MAX_TOKENS,
            ),
            timeout=settings.emotion_analysis_timeout_seconds,
        )
    except Exception:  # noqa: BLE001 —— 超时/网络/模型异常统一按失败处理
        _record_failure()
        logger.info("情绪分析失败（调用异常），跳过本轮记录 session=%s", session_id)
        return None

    analysis = parse_emotion_json(raw)
    if analysis is None:
        _record_failure()
        logger.info("情绪分析失败（JSON 解析/字段越界），跳过本轮记录 session=%s", session_id)
        return None
    _record_success()

    emotion = {
        "type": analysis.emotion,
        "intensity": analysis.intensity,
        "evidence": analysis.evidence,
        "risk_level": analysis.risk_level,  # P4：返回 risk_level 供 chat 链路做异步兜底
    }
    # 1) 回填 assistant 消息（会话详情可读，供前后端抽查一致）
    if mongo.db is not None:
        await mongo.db[COLL_MESSAGES].update_one(
            {"_id": assistant_message_id},
            {"$set": {"emotion": emotion}},
        )
        # 2) 写 emotion_records（仅记录结构化结果，不存对话原文）
        await mongo.db[COLL_EMOTION_RECORDS].insert_one(
            {
                "user_id": user_id,
                "source": "message",
                "ref_id": user_message_id,
                "emotion": analysis.emotion,
                "intensity": analysis.intensity,
                "evidence": analysis.evidence,
                "risk_level": analysis.risk_level,
                "strategy_hint": analysis.strategy_hint,
                "created_at": now_cst(),
            }
        )

    # P4 危机双保险：模型 risk_level=high 时异步兜底——即使本地词库未命中，
    # 也记录风险事件并升级会话状态，下一轮将展示危机卡片
    if analysis.risk_level == "high":
        from app.db.indexes import COLL_RISK_EVENTS

        await mongo.db[COLL_RISK_EVENTS].insert_one(
            {
                "user_id": user_id,
                "session_id": session_id,
                "level": "high",
                "trigger": "model",
                "matched": [analysis.evidence] if analysis.evidence else [],
                "created_at": now_cst(),
            }
        )
        # 升级会话危机状态
        await mongo.db[COLL_SESSIONS].update_one(
            {"_id": session_id},
            {"$set": {"crisis_high_shown": True}},
        )
        logger.warning(
            "模型 risk_level=high 兜底触发 user=%s session=%s",
            user_id, session_id,
        )

    return emotion


async def latest_session_emotion(session_id: ObjectId) -> dict | None:
    """返回本会话最近一条 assistant 消息的 emotion（供下一轮策略层注入）。"""
    if mongo.db is None:
        return None
    doc = await mongo.db[COLL_MESSAGES].find_one(
        {"session_id": session_id, "role": "assistant", "emotion": {"$ne": None}},
        sort=[("created_at", -1)],
    )
    return doc.get("emotion") if doc else None
