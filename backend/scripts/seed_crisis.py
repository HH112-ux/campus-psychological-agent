"""危机词库与求助资源种子脚本（P1 红线）。

用法（MongoDB 运行中）：
    .venv/bin/python -m scripts.seed_crisis
说明：
- 词库按 phrase 幂等 upsert（$setOnInsert），不覆盖运营在 DB 中对 enabled 的调整；
- 资源文档以代码内置为准同步（热线信息更新后重跑即可）。
"""
from __future__ import annotations

import asyncio

from app.core.timeutil import now_cst
from app.db.indexes import COLL_CRISIS_LEXICON, COLL_CRISIS_RESOURCES
from app.db.mongo import mongo
from app.services.crisis import normalize, refresh_lexicon_cache
from app.services.crisis_data import FALLBACK_RESOURCES, LEVEL1_PHRASES, LEVEL2_PHRASES


async def main() -> None:
    await mongo.connect()
    if not mongo.is_connected:
        print("[FAIL] MongoDB 未连接，请先启动 mongod")
        return
    db = mongo.db
    now = now_cst()

    l1_count = 0
    l2_count = 0
    for level, phrases, counter in (
        (1, LEVEL1_PHRASES, "l1"),
        (2, LEVEL2_PHRASES, "l2"),
    ):
        for phrase in phrases:
            key = normalize(phrase)
            res = await db[COLL_CRISIS_LEXICON].update_one(
                {"phrase": key},
                {"$setOnInsert": {"phrase": key, "level": level, "enabled": True,
                                  "source": "builtin", "created_at": now, "updated_at": now}},
                upsert=True,
            )
            if res.upserted_id is not None:
                if counter == "l1":
                    l1_count += 1
                else:
                    l2_count += 1

    await db[COLL_CRISIS_RESOURCES].update_one(
        {"_id": "current"},
        {"$set": {
            "version": FALLBACK_RESOURCES["version"],
            "updated_at": now,
            "updated_at_iso": FALLBACK_RESOURCES["updated_at"],
            "resources": FALLBACK_RESOURCES["resources"],
        }},
        upsert=True,
    )
    refresh_lexicon_cache()
    total = await db[COLL_CRISIS_LEXICON].count_documents({})
    print(f"[OK] 词库种子完成：本次新增一级 {l1_count} 条、二级 {l2_count} 条，"
          f"库内共 {total} 条；求助资源已同步（{len(FALLBACK_RESOURCES['resources'])} 条）")


if __name__ == "__main__":
    asyncio.run(main())
