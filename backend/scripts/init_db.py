"""建库建集合 + 索引初始化脚本（P0 验收：数据库结构就绪）。

用法（MongoDB 运行中）：
    .venv/bin/python -m scripts.init_db
"""
from __future__ import annotations

import asyncio

from app.db.indexes import COLL_CRISIS_LEXICON, COLL_CRISIS_RESOURCES, ensure_indexes
from app.db.mongo import mongo


async def main() -> None:
    await mongo.connect()
    if not mongo.is_connected:
        print("[FAIL] MongoDB 未连接，请先启动 mongod（见 README）")
        return
    db = mongo.db
    await ensure_indexes(db)
    # 预置两个配置集合（词库与求助资源 P1 使用，此处只建空集合）
    for coll in (COLL_CRISIS_LEXICON, COLL_CRISIS_RESOURCES):
        if coll not in await db.list_collection_names():
            await db.create_collection(coll)
    print("[OK] 集合与索引已就绪：", sorted(await db.list_collection_names()))


if __name__ == "__main__":
    asyncio.run(main())
