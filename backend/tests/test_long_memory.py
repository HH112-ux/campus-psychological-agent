"""V6 长期记忆测试：抽取解析 / 加密落库与去重 / fail-safe / 克制注入 / 接口行权 / 隐私一致。

DB 集成测试通过 client 夹具启动 lifespan（本地无 MongoDB 自动 skip）；
纯解析单测不依赖 DB。
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from bson import ObjectId

from app.config import get_settings
from app.core.crypto import decrypt
from app.core.timeutil import now_cst
from app.db.indexes import COLL_MEMORIES, COLL_USERS
from app.db.mongo import mongo
from app.services import chat, long_memory
from app.services.privacy import purge_expired_data
from tests.helpers import auth, create_session, login

# ---------- 纯解析单测（无 DB） ----------


def test_parse_tolerates_markdown_fence():
    raw = '```json\n{"memories": [{"kind": "person", "content": "ta 和室友小琳闹矛盾"}]}\n```'
    items = long_memory.parse_memory_json(raw)
    assert items == [{"kind": "person", "content": "ta 和室友小琳闹矛盾"}]


def test_parse_chinese_kind_alias():
    raw = '{"memories": [{"kind": "偏好", "content": "ta 喜欢睡前听轻音乐"}, {"kind": "情绪诱因", "content": "ta 一提到答辩就紧绷"}]}'
    items = long_memory.parse_memory_json(raw)
    assert [i["kind"] for i in items] == ["preference", "trigger"]


def test_parse_caps_at_three_and_dedups():
    raw = (
        '{"memories": ['
        '{"kind": "event", "content": "事件一"},'
        '{"kind": "event", "content": "事件一"},'
        '{"kind": "event", "content": "事件二"},'
        '{"kind": "event", "content": "事件三"},'
        '{"kind": "event", "content": "事件四"}]}'
    )
    items = long_memory.parse_memory_json(raw)
    assert len(items) == 3  # 批内去重 + 单轮 ≤3 条
    assert [i["content"] for i in items] == ["事件一", "事件二", "事件三"]


def test_parse_drops_bad_kind_and_truncates_content():
    raw = (
        '{"memories": ['
        '{"kind": "unknown", "content": "类别非法应丢弃"},'
        '{"kind": "person", "content": "' + "长" * 60 + '"}]}'
    )
    items = long_memory.parse_memory_json(raw)
    assert len(items) == 1
    assert len(items[0]["content"]) == long_memory.MAX_CONTENT_CHARS


def test_parse_empty_and_invalid():
    assert long_memory.parse_memory_json('{"memories": []}') == []
    assert long_memory.parse_memory_json("这不是 JSON") == []
    assert long_memory.parse_memory_json('{"memories": "not-a-list"}') == []


# ---------- 落库（加密 / 去重 / 上限） ----------


def _uid(client, openid=None):
    """取当前登录用户 _id；库内多用户时须传 openid 指定。

    注意 helpers.login 指定 openid 会改写全局 wx_mock_openid 且不还原，
    因此默认登录用户的 openid 不可假设，直接取库内唯一用户。
    """

    async def _fetch():
        query = {"openid": openid} if openid else {}
        doc = await mongo.db[COLL_USERS].find_one(query)
        return doc["_id"]

    return client.portal.call(_fetch)


def test_save_encrypts_and_dedups(client, db):
    login(client)
    uid = _uid(client)
    item = {"kind": "person", "content": "ta 和室友小琳最近闹矛盾"}

    assert client.portal.call(long_memory.save_memories, uid, ObjectId(), [item]) == 1

    async def _fetch():
        return await mongo.db[COLL_MEMORIES].find_one({"user_id": uid})

    doc = client.portal.call(_fetch)
    assert doc["content"] != item["content"]  # 应用层加密，不明文落库
    assert decrypt(doc["content"]) == item["content"]

    # 同一事实重复写入 → content_hash 去重，只刷新不新增
    assert client.portal.call(long_memory.save_memories, uid, ObjectId(), [item]) == 1

    async def _count():
        return await mongo.db[COLL_MEMORIES].count_documents({"user_id": uid})

    assert client.portal.call(_count) == 1


def test_save_enforces_cap(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "long_memory_max_items", 2)
    login(client)
    uid = _uid(client)
    for i in range(3):
        client.portal.call(
            long_memory.save_memories, uid, ObjectId(),
            [{"kind": "event", "content": f"事件编号{i}"}],
        )

    async def _count():
        return await mongo.db[COLL_MEMORIES].count_documents({"user_id": uid})

    assert client.portal.call(_count) == 2  # 超出上限删除最旧


# ---------- 抽取（fail-safe） ----------


def test_extract_fail_safe_on_provider_error(client, db, monkeypatch):
    async def boom(self, messages, temperature=0.7, max_tokens=1024):
        raise RuntimeError("模型异常")

    monkeypatch.setattr(long_memory.ZhipuProvider, "generate", boom)
    login(client)
    uid = _uid(client)
    saved = client.portal.call(long_memory.extract_and_save, uid, ObjectId(), "我和室友吵架了")
    assert saved == 0  # 任何异常按「本轮不写」处理


def test_extract_and_save_success(client, db, monkeypatch):
    async def gen(self, messages, temperature=0.7, max_tokens=1024):
        return '{"memories": [{"kind": "person", "content": "ta 和室友小琳最近闹矛盾"}]}'

    monkeypatch.setattr(long_memory.ZhipuProvider, "generate", gen)
    login(client)
    uid = _uid(client)
    assert client.portal.call(long_memory.extract_and_save, uid, ObjectId(), "我和室友吵架了") == 1

    listed = client.portal.call(long_memory.list_memories, uid)
    assert listed["total"] == 1
    assert listed["memories"][0]["content"] == "ta 和室友小琳最近闹矛盾"  # 服务端解密可读


def test_extract_disabled_by_switch(client, db, monkeypatch):
    async def gen(self, messages, temperature=0.7, max_tokens=1024):
        raise AssertionError("开关关闭后不应调用模型")

    monkeypatch.setattr(long_memory.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(get_settings(), "long_memory_enabled", False)
    login(client)
    uid = _uid(client)
    assert client.portal.call(long_memory.extract_and_save, uid, ObjectId(), "随便说说") == 0


# ---------- 克制注入 ----------


def _seed_two(client, uid):
    client.portal.call(
        long_memory.save_memories, uid, ObjectId(),
        [
            {"kind": "person", "content": "ta 和室友小琳最近因为作息闹矛盾"},
            {"kind": "preference", "content": "ta 喜欢睡前听轻音乐放松"},
        ],
    )


def test_injection_relevant_only(client, db):
    login(client)
    uid = _uid(client)
    _seed_two(client, uid)

    lines = client.portal.call(long_memory.build_injection, uid, "我和室友又吵架了")
    assert lines == ["ta 和室友小琳最近因为作息闹矛盾"]  # 无关的「轻音乐」不带出

    assert client.portal.call(long_memory.build_injection, uid, "今天天气怎么样") == []


def test_injection_caps(client, db, monkeypatch):
    login(client)
    uid = _uid(client)
    _seed_two(client, uid)

    monkeypatch.setattr(get_settings(), "long_memory_inject_max_items", 1)
    lines = client.portal.call(long_memory.build_injection, uid, "室友作息和轻音乐都提到了")
    assert len(lines) <= 1

    monkeypatch.setattr(get_settings(), "long_memory_inject_max_chars", 10)
    lines = client.portal.call(long_memory.build_injection, uid, "室友作息和轻音乐都提到了")
    assert sum(len(line) for line in lines) <= 10


# ---------- 接口行权（查看 / 删除 / 清空） ----------


def test_memory_api_flow(client, db):
    token = login(client)
    resp = client.get("/api/v1/memories", headers=auth(token))
    assert resp.json()["data"] == {"memories": [], "total": 0}

    uid = _uid(client)
    _seed_two(client, uid)

    listed = client.get("/api/v1/memories", headers=auth(token)).json()["data"]
    assert listed["total"] == 2
    contents = {m["content"] for m in listed["memories"]}
    assert "ta 和室友小琳最近因为作息闹矛盾" in contents

    mid = listed["memories"][0]["memory_id"]
    r = client.delete(f"/api/v1/memories/{mid}", headers=auth(token))
    assert r.status_code == 200 and r.json()["data"]["deleted"] is True

    r = client.delete(f"/api/v1/memories/{mid}", headers=auth(token))
    assert r.status_code == 404 and r.json()["code"] == 2001  # 不存在

    r = client.delete("/api/v1/memories", headers=auth(token))
    assert r.json()["data"]["deleted"] == 1
    assert client.get("/api/v1/memories", headers=auth(token)).json()["data"]["total"] == 0


def test_memory_isolated_between_users(client, db):
    token_a = login(client, "mock_mem_user_a")
    token_b = login(client, "mock_mem_user_b")
    uid_a = _uid(client, "mock_mem_user_a")
    _seed_two(client, uid_a)

    assert client.get("/api/v1/memories", headers=auth(token_b)).json()["data"]["total"] == 0

    mid_a = client.get("/api/v1/memories", headers=auth(token_a)).json()["data"]["memories"][0]["memory_id"]
    r = client.delete(f"/api/v1/memories/{mid_a}", headers=auth(token_b))
    assert r.status_code == 404  # B 不能删 A 的记忆


# ---------- 聊天主链路集成 ----------


def _send(client, token, sid, content):
    return client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": content, "stream": False},
        headers=auth(token),
    )


def test_chat_injects_relevant_memory(client, db, monkeypatch):
    captured = {}

    async def gen(self, messages, temperature=0.7, max_tokens=1024):
        if "长期记忆抽取器" in messages[0]["content"]:
            return '{"memories": []}'  # 后台抽取任务，固定返回空
        captured["messages"] = messages
        return "我在听，慢慢来。"

    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(get_settings(), "emotion_analysis_enabled", False)

    token = login(client)
    uid = _uid(client)
    _seed_two(client, uid)
    sid = create_session(client, token)

    r = _send(client, token, sid, "我和室友又吵架了")
    assert r.status_code == 200
    sys_prompt = captured["messages"][0]["content"]
    assert "【关于 ta 的长期记忆】" in sys_prompt
    assert "室友小琳" in sys_prompt
    assert "轻音乐" not in sys_prompt  # 无关记忆不注入


def test_chat_schedules_extraction(client, db, monkeypatch):
    async def gen(self, messages, temperature=0.7, max_tokens=1024):
        if "长期记忆抽取器" in messages[0]["content"]:
            return '{"memories": [{"kind": "偏好", "content": "ta 喜欢睡前听轻音乐"}]}'
        return "我在听，慢慢来。"

    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)
    monkeypatch.setattr(get_settings(), "emotion_analysis_enabled", False)

    token = login(client)
    uid = _uid(client)
    sid = create_session(client, token)

    r = _send(client, token, sid, "最近我发现睡前听轻音乐能放松下来")
    assert r.status_code == 200

    client.portal.call(asyncio.sleep, 0.3)  # 让后台抽取任务跑完
    listed = client.portal.call(long_memory.list_memories, uid)
    assert listed["total"] == 1
    assert listed["memories"][0]["kind"] == "preference"


def test_high_crisis_skips_extraction(client, db, monkeypatch):
    calls = {"extract": 0}

    async def gen(self, messages, temperature=0.7, max_tokens=1024):
        if "长期记忆抽取器" in messages[0]["content"]:
            calls["extract"] += 1
        return "我在听。"

    monkeypatch.setattr(chat.ZhipuProvider, "generate", gen)

    token = login(client)
    uid = _uid(client)
    sid = create_session(client, token)

    r = _send(client, token, sid, "我不想活了")
    assert r.json()["data"]["risk_level"] == "high"

    client.portal.call(asyncio.sleep, 0.2)
    assert calls["extract"] == 0  # 危机内容不进入长期记忆

    async def _count():
        return await mongo.db[COLL_MEMORIES].count_documents({"user_id": uid})

    assert client.portal.call(_count) == 0


# ---------- 隐私一致（导出 / 物理删除） ----------


def test_export_includes_memories(client, db):
    token = login(client)
    uid = _uid(client)
    _seed_two(client, uid)

    data = client.get("/api/v1/users/me/data/export", headers=auth(token)).json()["data"]
    assert "memories" in data
    contents = {m["content"] for m in data["memories"]}
    assert "ta 和室友小琳最近因为作息闹矛盾" in contents  # 导出为解密后可读文本


def test_purge_deletes_memories(client, db):
    openid = "mock_purge_memory_user"
    token = login(client, openid)
    uid = _uid(client, openid)
    _seed_two(client, uid)

    resp = client.request(
        "DELETE", "/api/v1/users/me/data",
        json={"confirm_text": "删除"}, headers=auth(token),
    )
    assert resp.status_code == 200

    async def _expire_and_purge():
        await mongo.db[COLL_USERS].update_one(
            {"_id": uid}, {"$set": {"erase_at": now_cst() - timedelta(seconds=1)}}
        )
        purged = await purge_expired_data()
        remaining = await mongo.db[COLL_MEMORIES].count_documents({"user_id": uid})
        return purged, remaining

    purged, remaining = client.portal.call(_expire_and_purge)
    assert purged == 1
    assert remaining == 0  # 到期物理删除涵盖长期记忆
