"""V1 反馈闭环：bad-case 收集与汇总测试（services/bad_cases.py）。

覆盖：只收点踩、配对触发用户消息（时间序取最近一条）、会话标题关联、
--days 窗口过滤、原因聚合计数。dev/test 无加密密钥，内容明文往返。
"""
from __future__ import annotations

import os
from datetime import timedelta

import pymongo
import pytest
from bson import ObjectId

from app.core.timeutil import now_cst
from app.db.indexes import COLL_MESSAGES, COLL_SESSIONS, COLL_USERS
from app.services import bad_cases


def _sync_db():
    client = pymongo.MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    return client, client[os.environ.get("MONGODB_DB", "xinyu_test")]


@pytest.fixture()
def seeded(db):
    """种子：1 用户 1 会话，3 条 assistant 反馈消息（2 点踩 1 点赞）+ 各自触发用户消息。"""
    client, sdb = _sync_db()
    now = now_cst()
    uid, sid = ObjectId(), ObjectId()
    sdb[COLL_USERS].insert_one({"_id": uid, "openid": "mock_test_user"})
    sdb[COLL_SESSIONS].insert_one(
        {"_id": sid, "user_id": uid, "title": "考试焦虑", "status": "active", "created_at": now}
    )

    def msg(role, content, ts, feedback=None):
        doc = {
            "_id": ObjectId(),
            "session_id": sid,
            "role": role,
            "content": content,  # test 无密钥，明文存储
            "created_at": ts,
        }
        if feedback:
            doc["feedback"] = feedback
        sdb[COLL_MESSAGES].insert_one(doc)
        return doc

    # 案例 1（窗口内，点踩 preachy）
    msg("user", "我考试好紧张", now - timedelta(days=2, minutes=1))
    msg("assistant", "你要放松心态，劳逸结合", now - timedelta(days=2),
        feedback={"rating": "dislike", "reason": "preachy"})
    # 案例 2（窗口内，点踩 no_help）
    msg("user", "还是睡不着", now - timedelta(days=1, minutes=1))
    msg("assistant", "喝杯牛奶吧", now - timedelta(days=1),
        feedback={"rating": "dislike", "reason": "no_help"})
    # 案例 3（窗口内，点赞 —— 不应被收集）
    msg("user", "谢谢", now - timedelta(hours=12, minutes=1))
    msg("assistant", "不客气，我在", now - timedelta(hours=12),
        feedback={"rating": "like", "reason": None})
    # 案例 4（窗口外 30 天前的点踩 —— 近 14 天窗口不应收集，全量应收）
    msg("user", "旧烦恼", now - timedelta(days=30, minutes=1))
    msg("assistant", "旧回复", now - timedelta(days=30),
        feedback={"rating": "dislike", "reason": "other"})

    client.close()
    return {"uid": uid, "sid": sid}


def test_collect_in_window_pairs_trigger_message(client, seeded):
    """近 14 天窗口：收 2 条点踩，正确配对触发用户消息与会话标题。"""
    cases = client.portal.call(bad_cases.collect_bad_cases, bad_cases.default_since(14))
    assert len(cases) == 2
    first, second = cases  # 按时间正序
    assert first["reason"] == "preachy"
    assert first["user_message"] == "我考试好紧张"
    assert first["assistant_reply"] == "你要放松心态，劳逸结合"
    assert first["session_title"] == "考试焦虑"
    assert second["reason"] == "no_help"
    assert second["user_message"] == "还是睡不着"


def test_collect_all_includes_out_of_window(client, seeded):
    """全量导出（since=None）：含 30 天前的旧点踩，不含点赞。"""
    cases = client.portal.call(bad_cases.collect_bad_cases, None)
    assert len(cases) == 3
    assert all(c["reason"] in ("preachy", "no_help", "other") for c in cases)
    assert cases[0]["assistant_reply"] == "旧回复"  # 正序：最旧的 30 天前案例在首位


def test_summarize_counts_by_reason(client, seeded):
    """原因聚合计数（降序），供复盘样本概览。"""
    cases = client.portal.call(bad_cases.collect_bad_cases, None)
    summary = bad_cases.summarize(cases)
    assert summary["total"] == 3
    assert summary["by_reason"] == {"preachy": 1, "no_help": 1, "other": 1}
