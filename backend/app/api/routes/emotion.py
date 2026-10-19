"""情绪数据接口（对齐《API 文档》第 7 节：今日打卡 / 每日打卡 / 情绪记录 / 情绪趋势）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user
from app.core.responses import ok_response
from app.models.emotion import CheckinCreate
from app.services import checkins, emotion_logs

router = APIRouter(prefix="/api/v1/emotion", tags=["emotion"])


@router.get("/checkins/today")
async def checkin_today(current_user: dict = Depends(get_current_user)):
    """今日打卡；无记录时 data 为 null（首页据此渲染打卡区或已打卡卡片）。"""
    return ok_response(await checkins.get_today(current_user["_id"]))


@router.post("/checkins")
async def create_checkin(
    body: CheckinCreate, current_user: dict = Depends(get_current_user)
):
    """每日打卡；同一天重复提交视为修改（updated=true），日期以服务器时区为准。"""
    return ok_response(
        await checkins.upsert_checkin(current_user["_id"], body.mood, body.note)
    )


@router.get("/records")
async def emotion_records(
    start: str | None = Query(None, description="起始日期 yyyy-mm-dd，默认近 30 天"),
    end: str | None = Query(None, description="结束日期 yyyy-mm-dd（含当日）"),
    emotion: str | None = Query(None, description="按情绪类别筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """情绪记录时间线：合并对话来源与打卡来源，按时间倒序分页。"""
    return ok_response(
        await emotion_logs.list_records(
            current_user["_id"], start, end, emotion, page, page_size
        )
    )


@router.get("/trends")
async def emotion_trends(
    granularity: str = Query("day", description="day | week | month"),
    days: int = Query(7, ge=7, le=30),
    current_user: dict = Depends(get_current_user),
):
    """趋势聚合：均值与主导情绪在服务端计算，小程序只渲染。"""
    return ok_response(
        await emotion_logs.get_trends(current_user["_id"], days, granularity)
    )


@router.get("/weekly-insight")
async def weekly_insight(
    days: int = Query(7, ge=7, le=30),
    current_user: dict = Depends(get_current_user),
):
    """V2 周报洞察：描述性「本周情绪小结」（只陈述现象、不做归因）。"""
    return ok_response(
        await emotion_logs.get_weekly_insight(current_user["_id"], days)
    )
