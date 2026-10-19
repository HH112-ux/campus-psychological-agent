"""语音接口（V5）：录音上传 → 转写为文字（不落原始音频）。

契约（API 文档 §10）：
- 请求：`multipart/form-data`，字段 `file` 为录音文件（mp3/aac 等）；
- 响应：`{ "code": 0, "data": { "text": "识别出的文字" } }`；
- 转写结果交由用户确认（可编辑）后，再作为普通消息经发送消息接口进入对话主链路
  （内容安全、危机拦截、情绪识别都在该链路上，语音不另开旁路）。
- 合规：音频仅用于本次转写，转写后即弃，不落库不落盘；失败时降级为键盘输入。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.deps import get_current_user
from app.core.responses import ok_response
from app.services import speech

router = APIRouter(prefix="/api/v1/speech", tags=["speech"])


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(..., description="录音文件（mp3/aac 等）"),
    current_user: dict = Depends(get_current_user),
):
    """语音转文字：音频只用于本次转写，转写后即弃。"""
    audio = await file.read()
    text = await speech.transcribe(audio, file.content_type)
    return ok_response({"text": text})
