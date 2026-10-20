"""长期记忆接口（V6）：查看 / 删除 / 清空，延续 PIPL 行权（对齐 API 文档第 11 节）。

记忆内容与对话一致采用应用层加密存储，本接口在服务端解密后返回可读文本；
用户可随时删除单条或清空全部——与 M3 的删除机制同源（数据导出与到期物理删除均纳入）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.exceptions import CODE_NOT_FOUND, BizError
from app.core.responses import ok_response
from app.db.oid import parse_oid
from app.services import long_memory

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


@router.get("")
async def list_memories(current_user: dict = Depends(get_current_user)):
    """查看该用户的长期记忆（按最近更新倒序；无记录时 memories 为空数组）。"""
    return ok_response(await long_memory.list_memories(current_user["_id"]))


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, current_user: dict = Depends(get_current_user)):
    """删除单条记忆；不存在或不属于该用户返回 2001（HTTP 404）。"""
    deleted = await long_memory.delete_memory(current_user["_id"], parse_oid(memory_id))
    if not deleted:
        raise BizError(CODE_NOT_FOUND, "记忆不存在", http_status=404)
    return ok_response({"memory_id": memory_id, "deleted": True})


@router.delete("")
async def clear_memories(current_user: dict = Depends(get_current_user)):
    """清空该用户全部长期记忆，返回删除条数。"""
    return ok_response({"deleted": await long_memory.clear_memories(current_user["_id"])})
