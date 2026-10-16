"""微信内容安全（msgSecCheck）文本过检（M1 / G9，微信提审要求）。

- 命中违规（errcode=87014 或 result.suggest=risky）：抛 BizError(2006)，消息不落库、不计限流；
- suggest=review：放行——1v1 倾诉场景没有人审队列，心理表达易被误伤，拦截代价高于放行；
- 跳过：开关关闭 / mock 登录 / 未配置 AppID/Secret（dev 与测试默认不阻塞）；
- 网络/接口异常：fail-open（warning 日志）——安检不可用不应阻断对话主链路；
- token 失效（40001/40014/42001）：强制刷新 access_token 后重试一次。
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.core.exceptions import CODE_CONTENT_RISKY, BizError
from app.services import wechat

logger = logging.getLogger(__name__)

# token 类错误码：access_token 无效/过期
_TOKEN_ERRCODES = {40001, 40014, 42001}
# msgSecCheck v2 场景值：2=评论/对话类文本
_SCENE_CHAT = 2


async def _request_msg_sec_check(token: str, content: str, openid: str) -> dict:
    """调用 msgSecCheck v2（独立成函数便于测试打桩）。"""
    settings = get_settings()
    payload = {"content": content, "version": 2, "scene": _SCENE_CHAT, "openid": openid}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            settings.wx_msg_sec_check_url, params={"access_token": token}, json=payload
        )
    return resp.json()


def _is_risky(data: dict) -> bool:
    if data.get("errcode") == 87014:
        return True
    return (data.get("result") or {}).get("suggest") == "risky"


async def check_text(content: str, openid: str) -> None:
    """对单条用户文本过检；命中违规抛 2006，其余情况（放行/跳过/异常）正常返回。"""
    settings = get_settings()
    if (
        not settings.wx_content_check_enabled
        or settings.wx_mock_login
        or not settings.wx_appid
        or not settings.wx_secret
    ):
        return

    try:
        token = await wechat.get_access_token()
        data = await _request_msg_sec_check(token, content, openid)
        if data.get("errcode") in _TOKEN_ERRCODES:
            # token 失效：强制刷新后重试一次
            token = await wechat.get_access_token(force_refresh=True)
            data = await _request_msg_sec_check(token, content, openid)
            if data.get("errcode") in _TOKEN_ERRCODES:
                logger.warning(
                    "msgSecCheck token 刷新后仍失败 errcode=%s，本轮按放行处理",
                    data.get("errcode"),
                )
                return
    except Exception:
        logger.warning("msgSecCheck 调用失败，本轮按放行处理（fail-open）", exc_info=True)
        return

    if _is_risky(data):
        label = (data.get("result") or {}).get("label")
        logger.info("msgSecCheck 命中违规已拦截（label=%s）", label)
        raise BizError(
            CODE_CONTENT_RISKY,
            "消息包含不适合发送的内容，调整一下再发吧",
            http_status=422,
        )
