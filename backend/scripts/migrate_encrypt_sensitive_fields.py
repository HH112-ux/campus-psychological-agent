"""历史明文敏感字段加密迁移（幂等，可重复执行）。

覆盖字段：
- emotion_records.evidence            情绪分析原文摘录
- messages.emotion.evidence           助手消息上回填的情绪摘录
- checkins.note                       打卡备注
- risk_events.matched[]               风险事件命中词（模型兜底时为原句摘录）

用法（必须配置 DATA_ENCRYPTION_KEY，否则拒绝执行）：
    .venv/bin/python -m scripts.migrate_encrypt_sensitive_fields --dry-run
    .venv/bin/python -m scripts.migrate_encrypt_sensitive_fields

说明：
- 已加密记录（dict 结构）自动跳过，重复执行不会二次加密；
- 空值/None 原样保留；
- 每处理 batch-size 条提交一次，可中断后重跑。
"""
from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.core.crypto import decrypt, encrypt_optional_text, is_encrypted
from app.db.indexes import COLL_CHECKINS, COLL_EMOTION_RECORDS, COLL_MESSAGES, COLL_RISK_EVENTS
from app.db.mongo import mongo


async def _migrate_text_field(coll: str, field: str, dry_run: bool) -> int:
    """迁移集合中的单层文本字段，返回实际（或 dry-run 下将会）更新的条数。"""
    db = mongo.db
    changed = 0
    async for doc in db[coll].find({field: {"$exists": True, "$nin": [None, ""]}}):
        value = doc.get(field)
        if not isinstance(value, str) or is_encrypted(value):
            continue
        changed += 1
        if dry_run:
            continue
        await db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: encrypt_optional_text(value)}},
        )
    return changed


async def _migrate_message_emotion(dry_run: bool) -> int:
    """迁移 messages.emotion.evidence（嵌套字段）。"""
    db = mongo.db
    changed = 0
    async for doc in db[COLL_MESSAGES].find({"emotion.evidence": {"$exists": True, "$nin": [None, ""]}}):
        evidence = (doc.get("emotion") or {}).get("evidence")
        if not isinstance(evidence, str) or is_encrypted(evidence):
            continue
        changed += 1
        if dry_run:
            continue
        await db[COLL_MESSAGES].update_one(
            {"_id": doc["_id"]},
            {"$set": {"emotion.evidence": encrypt_optional_text(evidence)}},
        )
    return changed


async def _migrate_risk_matched(dry_run: bool) -> int:
    """迁移 risk_events.matched 列表中的明文命中词。"""
    db = mongo.db
    changed = 0
    async for doc in db[COLL_RISK_EVENTS].find({"matched": {"$exists": True}}):
        matched = doc.get("matched") or []
        if not isinstance(matched, list):
            continue
        migrated = [
            item
            if not isinstance(item, str) or not item or is_encrypted(item)
            else encrypt_optional_text(item)
            for item in matched
        ]
        if migrated == matched:
            continue
        changed += 1
        if dry_run:
            continue
        await db[COLL_RISK_EVENTS].update_one(
            {"_id": doc["_id"]},
            {"$set": {"matched": migrated}},
        )
    return changed


async def _verify_sample() -> bool:
    """抽样解密校验，确认迁移后的密文可被当前密钥还原。"""
    doc = await mongo.db[COLL_EMOTION_RECORDS].find_one(
        {"evidence": {"$type": "object"}}
    )
    if doc is None:
        return True
    try:
        return isinstance(decrypt(doc["evidence"]), str)
    except Exception:  # noqa: BLE001 - 迁移脚本需明确报告密钥不匹配
        return False


async def main(dry_run: bool) -> None:
    if not get_settings().data_encryption_key:
        print("[FAIL] DATA_ENCRYPTION_KEY 未配置：拒绝执行，避免把明文误判为完成迁移")
        return

    await mongo.connect()
    if not mongo.is_connected:
        print("[FAIL] MongoDB 未连接，请先启动 mongod / 检查 MONGODB_URI")
        return

    counts = {
        "emotion_records.evidence": await _migrate_text_field(
            COLL_EMOTION_RECORDS, "evidence", dry_run
        ),
        "messages.emotion.evidence": await _migrate_message_emotion(dry_run),
        "checkins.note": await _migrate_text_field(COLL_CHECKINS, "note", dry_run),
        "risk_events.matched": await _migrate_risk_matched(dry_run),
    }
    mode = "DRY-RUN" if dry_run else "DONE"
    for name, count in counts.items():
        print(f"[{mode}] {name}: {count} 条")
    if not dry_run and not await _verify_sample():
        print("[FAIL] 抽样解密失败：请确认 DATA_ENCRYPTION_KEY 与历史数据一致")
        return
    print(f"[{mode}] 迁移完成，可重复执行（已加密记录会自动跳过）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史明文敏感字段加密迁移")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
