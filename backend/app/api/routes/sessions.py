"""会话接口（对齐 API 文档第 5 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user
from app.core.responses import ok_response
from app.core.timeutil import to_iso
from app.models.session import SessionCreate, SessionRename
from app.services import sessions as svc

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    return ok_response(await svc.list_sessions(current_user["_id"], page, page_size))


@router.post("", status_code=201)
async def create_session(body: SessionCreate, current_user: dict = Depends(get_current_user)):
    s = await svc.create_session(current_user["_id"], body.title)
    return ok_response(
        {
            "session_id": str(s["_id"]),
            "title": s.get("title") or "新的对话",
            "rounds": 0,
            "status": "active",
            "created_at": to_iso(s["created_at"]),
        },
        status_code=201,
    )


@router.get("/{session_id}")
async def session_detail(session_id: str, current_user: dict = Depends(get_current_user)):
    return ok_response(await svc.get_detail(session_id, current_user["_id"]))


@router.patch("/{session_id}")
async def rename_session(
    session_id: str, body: SessionRename, current_user: dict = Depends(get_current_user)
):
    s = await svc.rename_session(session_id, current_user["_id"], body.title)
    return ok_response(svc.serialize_session_brief(s))


@router.delete("/{session_id}")
async def delete_session(session_id: str, current_user: dict = Depends(get_current_user)):
    await svc.delete_session(session_id, current_user["_id"])
    return ok_response(None, message="已删除")
