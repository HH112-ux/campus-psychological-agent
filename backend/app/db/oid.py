"""ObjectId 解析 helper：把 24 位 hex 字符串安全转为 ObjectId。"""
from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId

from app.core.exceptions import CODE_NOT_FOUND, BizError


def parse_oid(oid: str) -> ObjectId:
    """非法 id 一律表现为“资源不存在”，避免泄漏细节。"""
    try:
        return ObjectId(oid)
    except (InvalidId, TypeError):
        raise BizError(CODE_NOT_FOUND, "资源不存在", http_status=404)
