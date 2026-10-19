"""V4 练习卡片测试：目录红线 / 目录接口 / 完成落库与统计 / 未知练习处理。"""
from __future__ import annotations

from app.db.indexes import COLL_PRACTICE_LOGS
from app.db.mongo import mongo
from app.services import practices
from tests.helpers import auth, login


def test_catalog_content_red_lines():
    """目录含四类卡片；文案不含医疗/诊断/疗效表述；均标记待专业审校。"""
    ids = {c["id"] for c in practices.CATALOG}
    assert {"breath_478", "breath_box", "mindful_3min", "activate_micro"} <= ids
    forbidden = ("诊断", "治疗", "疗效", "治愈", "医疗")
    for card in practices.CATALOG:
        assert card["reviewed"] is False
        blob = (
            card["title"]
            + card["subtitle"]
            + "".join(card.get("steps", []))
            + "".join(card.get("tasks", []))
        )
        assert not any(w in blob for w in forbidden), card["id"]


def test_list_practices_empty_today(client, db):
    token = login(client)
    resp = client.get("/api/v1/practices", headers=auth(token))
    data = resp.json()["data"]
    assert len(data["practices"]) == len(practices.CATALOG)
    assert data["completed_today"] == []
    assert all(p["completed_today"] is False for p in data["practices"])


def test_complete_practice_flow(client, db):
    """完成 → 计数递增 → 目录标记已完成。"""
    token = login(client)
    resp = client.post(
        "/api/v1/practices/breath_478/complete", json={}, headers=auth(token)
    )
    data = resp.json()["data"]
    assert data["completed"] is True and data["times_today"] == 1

    resp = client.post(
        "/api/v1/practices/breath_478/complete",
        json={"duration_seconds": 90},
        headers=auth(token),
    )
    assert resp.json()["data"]["times_today"] == 2

    listed = client.get("/api/v1/practices", headers=auth(token)).json()["data"]
    assert "breath_478" in listed["completed_today"]
    card = next(p for p in listed["practices"] if p["id"] == "breath_478")
    assert card["completed_today"] is True


def test_complete_default_duration(client, db):
    """未传时长时用卡片建议时长；落库含类别。"""
    token = login(client)
    client.post(
        "/api/v1/practices/mindful_3min/complete", json={}, headers=auth(token)
    )

    async def _fetch():
        return await mongo.db[COLL_PRACTICE_LOGS].find_one({"practice_id": "mindful_3min"})

    doc = client.portal.call(_fetch)
    assert doc["duration_seconds"] == 180
    assert doc["category"] == "mindfulness"


def test_complete_unknown_practice(client, db):
    token = login(client)
    resp = client.post(
        "/api/v1/practices/not_exist/complete", json={}, headers=auth(token)
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 2001
