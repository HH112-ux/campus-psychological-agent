"""消息接口：发送消息（流式/非流式）、点赞点踩（对齐 API 文档第 6/9 节）。"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.core.deps import get_consented_user
from app.core.exceptions import (
    CODE_BUSINESS_VALIDATION,
    CODE_MODEL_UNAVAILABLE,
    BizError,
)
from app.core.responses import ok_response
from app.core.timeutil import now_cst, to_iso
from app.db.oid import parse_oid
from app.models.message import FeedbackRequest, MessageSend
from app.services import chat
from app.services import messages as messages_svc
from app.services import sessions as sessions_svc
from app.services.crisis import get_resources

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["messages"])

# 持有中继任务强引用（与 chat._background_tasks 同理）
_relay_tasks: set[asyncio.Task] = set()

# prepare 阶段（读会话 / 落库 / 危机检测）异常时的降级文案：
# 用户已经发出消息，不能只回一个 500；至少把内置求助热线递到面前。
PREPARE_FAILED_REPLY = (
    "我这边刚刚没接住你的消息，你愿意再发一次吗？如果现在很难受，可以先拨下面的电话。"
)


async def _degraded_payload() -> dict:
    """DB 不可用时的降级响应：结构与正常非流式响应一致，附带内置热线卡片。"""
    resources = (await get_resources())["resources"]
    return {
        "message_id": "",
        "assistant_reply": PREPARE_FAILED_REPLY,
        "emotion": None,
        "risk_level": "none",
        "crisis": {"level": "mid", "show_card": True, "resources": resources},
        "degraded": True,
        "created_at": to_iso(now_cst()),
    }


def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _with_heartbeat(events, interval: float):
    """把业务事件与心跳帧合并输出。

    模型首包可能慢于小程序端 10s idle 超时（服务端读超时 30s），若无任何下行，
    前端会把手机会正常的慢响应当成断线并 abort。这里按固定间隔下发 ping，
    小程序端收到任意分片都会重置 idle 计时（utils/sse.js）。ping 事件未被业务
    分支识别，等同忽略。

    生成放在独立任务里：消费者（HTTP 连接）断开时只停止读取，生成任务继续跑完
    并落库，避免断连丢回复。
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def _produce() -> None:
        try:
            async for item in events:
                await queue.put(("event", item))
        except Exception as exc:  # noqa: BLE001 —— 交给消费侧统一出 error 帧
            await queue.put(("error", exc))
        finally:
            await queue.put(("end", None))

    producer = asyncio.create_task(_produce())
    _relay_tasks.add(producer)
    producer.add_done_callback(_relay_tasks.discard)

    while True:
        try:
            kind, payload = await asyncio.wait_for(queue.get(), timeout=interval)
        except TimeoutError:
            yield "ping", {"ts": int(time.time())}
            continue
        if kind == "end":
            return
        if kind == "error":
            raise payload
        yield payload


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str, body: MessageSend, current_user: dict = Depends(get_consented_user)
):
    # 先校验归属并完成 prepare（长度/轮次/限流/危机），错误以普通 JSON 返回；
    # 内部/DB 异常不抛 500：降级为带内置热线的回复，保证求助入口始终可用
    try:
        session = await sessions_svc.get_owned_session(session_id, current_user["_id"])
        turn = await chat.prepare_turn(current_user, session, body.content)
    except BizError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("prepare_turn 失败，降级为带求助热线的回复")
        payload = await _degraded_payload()

        if not body.stream or not get_settings().stream_enabled:
            return ok_response(payload)

        async def degraded_stream():
            yield _sse_frame("crisis", payload["crisis"])
            yield _sse_frame("delta", {"content": payload["assistant_reply"]})
            yield _sse_frame("done", {"message_id": "", "degraded": True, "truncated": False})

        return StreamingResponse(
            degraded_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # P5 降级开关：stream_enabled=false 时统一走非流式 JSON 路径
    if not body.stream or not get_settings().stream_enabled:
        return ok_response(await chat.reply_nonstream(turn))

    async def event_generator():
        try:
            async for event, data in _with_heartbeat(
                chat.stream_events(turn), get_settings().sse_heartbeat_seconds
            ):
                yield _sse_frame(event, data)
        except Exception:  # noqa: BLE001
            yield _sse_frame(
                "error", {"code": CODE_MODEL_UNAVAILABLE, "message": "服务繁忙，请稍后再试"}
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/messages/{message_id}/feedback")
async def message_feedback(
    message_id: str, body: FeedbackRequest, current_user: dict = Depends(get_consented_user)
):
    if body.rating == "dislike" and not body.reason:
        raise BizError(CODE_BUSINESS_VALIDATION, "点踩时需要选择一个原因", http_status=400)

    await messages_svc.record_feedback(
        parse_oid(message_id), current_user["_id"], body.rating, body.reason
    )
    message = "已记录，谢谢你的反馈，我会改进" if body.rating == "dislike" else "谢谢你的认可"
    return ok_response(None, message=message)
