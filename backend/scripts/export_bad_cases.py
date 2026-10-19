"""V1 反馈闭环：bad-case（点踩）导出脚本，供双周复盘人工归类。

用法（backend/ 目录，MongoDB 运行中）：
    .venv/bin/python scripts/export_bad_cases.py              # 近 14 天（对齐双周节奏）
    .venv/bin/python scripts/export_bad_cases.py --days 30    # 近 30 天
    .venv/bin/python scripts/export_bad_cases.py --all        # 全量
    .venv/bin/python scripts/export_bad_cases.py --out /tmp/bad-cases.json

隐私红线：
- 输出含解密后的对话内容（用户消息 + AI 回复），仅供复盘归类使用；
- 导出文件严禁提交 Git（.gitignore 已加 bad-cases*.json 防御），复盘后妥善删除；
- 复盘留档只记归因与迭代项，不粘贴原文（模板见 docs/bad-case-review-template.md）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.mongo import mongo  # noqa: E402
from app.services.bad_cases import collect_bad_cases, default_since, summarize  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="导出 bad-case（点踩）供双周复盘")
    parser.add_argument("--days", type=int, default=14, help="导出近 N 天（默认 14）")
    parser.add_argument("--all", action="store_true", help="全量导出（忽略 --days）")
    parser.add_argument("--out", type=str, default="", help="输出文件路径（默认输出到 stdout）")
    args = parser.parse_args()

    await mongo.connect()
    if not mongo.is_connected:
        print("[FAIL] MongoDB 未连接，请先启动 mongod", file=sys.stderr)
        return 1
    try:
        since = None if args.all else default_since(args.days)
        cases = await collect_bad_cases(since)
    finally:
        await mongo.disconnect()

    payload = {
        "window": "all" if args.all else f"last_{args.days}_days",
        "summary": summarize(cases),
        "cases": cases,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"已导出 {len(cases)} 条 bad-case → {args.out}")
        print("注意：文件含解密对话内容，严禁提交 Git，复盘后请妥善删除。")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
