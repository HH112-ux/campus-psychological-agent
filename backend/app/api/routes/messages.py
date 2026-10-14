"""消息接口：发送消息（流式/非流式）、点赞点踩（对齐 API 文档第 6/9 节）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.exceptions import (
    CODE_BUSINESS_VALIDATION,
    CODE_MODEL_UNAVAILABLE,
    CODE_NOT_FOUND,
    CODE_RESOURCE_FORBIDDEN,
    BizError,
)
from app.core.responses import ok_response
from app.db.indexes import COLL_MESSAGES, COLL_SESSIONS
from app.db.mongo import mongo
from app.db.oid import parse_oid
from app.models.message import FeedbackRequest, MessageSend
from app.services import chat
from app.services import sessions as sessions_svc

router = APIRouter(prefix="/api/v1", tags=["messages"])


def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str, body: MessageSend, current_user: dict = Depends(get_current_user)
):
    # 先校验归属并完成 prepare（长度/轮次/限流/危机），错误以普通 JSON 返回
    session = await sessions_svc.get_owned_session(session_id, current_user["_id"])
    turn = await chat.prepare_turn(current_user, session, body.content)

    # P5 降级开关：stream_enabled=false 时统一走非流式 JSON 路径
    if not body.stream or not get_settings().stream_enabled:
        return ok_response(await chat.reply_nonstream(turn))

    async def event_generator():
        try:
            async for event, data in chat.stream_events(turn):
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
    message_id: str, body: FeedbackRequest, current_user: dict = Depends(get_current_user)
):
    if body.rating == "dislike" and not body.reason:
        raise BizError(CODE_BUSINESS_VALIDATION, "点踩时需要选择一个原因", http_status=400)

    msg = await mongo.db[COLL_MESSAGES].find_one(
        {"_id": parse_oid(message_id), "role": "assistant"}
    )
    if msg is None:
        raise BizError(CODE_NOT_FOUND, "回复不存在", http_status=404)
    session = await mongo.db[COLL_SESSIONS].find_one({"_id": msg.get("session_id")})
    if session is None or session.get("user_id") != current_user["_id"]:
        raise BizError(CODE_RESOURCE_FORBIDDEN, "回复不存在", http_status=404)

    await mongo.db[COLL_MESSAGES].update_one(
        {"_id": msg["_id"]}, {"$set": {"feedback": {"rating": body.rating, "reason": body.reason}}}
    )
    message = "已记录，谢谢你的反馈，我会改进" if body.rating == "dislike" else "谢谢你的认可"
    return ok_response(None, message=message)
