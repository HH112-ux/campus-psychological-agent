"""V6 长期记忆抽取稳定性评估（E1 回归门）。

用法（backend/ 目录，需 .env 中的 ZHIPU_API_KEY）：
    .venv/bin/python scripts/eval_long_memory.py          # 出报告，永远退出 0
    .venv/bin/python scripts/eval_long_memory.py --gate   # E1 回归门：综合命中率 < 80% 退出 1
    未配置 ZHIPU_API_KEY 时打印 SKIP 并退出 0（CI 无 secret 环境不阻塞）

- 评估集：scripts/eval-data/memory_eval_v1.json（正向 12 + 对抗 6：一次性情绪/
  危机内容/闲聊/琐事/反讽/他人事件，随 bad-case 按 docs/eval-gate.md §4 约定扩充）
- 链路与线上一致：轻量档模型、temperature 0.2、同一抽取指令与解析器
  （app/services/long_memory.py 的 _EXTRACT_SYSTEM_INSTRUCTION / parse_memory_json）
- 指标：
  · 综合命中率（每条样本是否满足期望：正向命中 kind+关键词、对抗输出空）——主指标，≥80% 达标
  · 输出可解析率（字段合法率，辅助口径）
  · 类别正确率（仅正向样本，kind 命中，不看关键词，辅助口径）
- 输出：docs/memory-eval-v6.md（滚动基线）
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.llm.zhipu import ZhipuProvider  # noqa: E402
from app.services.long_memory import (  # noqa: E402
    _EXTRACT_SYSTEM_INSTRUCTION,
    _extract_json,
    parse_memory_json,
)

EVAL_FILE = Path(__file__).resolve().parent / "eval-data" / "memory_eval_v1.json"
REPORT_FILE = Path(__file__).resolve().parents[2] / "docs" / "memory-eval-v6.md"

KIND_ZH = {
    "person": "人物",
    "event": "事件",
    "preference": "偏好",
    "trigger": "情绪诱因",
}
HIT_THRESHOLD = 0.8  # go/no-go 阈值（E1 回归门：--gate 时低于此值退出 1）


def _judge(expect: list[dict], items: list[dict]) -> tuple[bool, bool]:
    """返回 (综合命中, 类别命中)。对抗样本（expect 为空）：不抽即命中。"""
    if not expect:
        return (len(items) == 0), (len(items) == 0)
    kind_hit = any(i["kind"] == e["kind"] for i in items for e in expect)
    full_hit = any(
        i["kind"] == e["kind"] and (not e.get("keyword") or e["keyword"] in i["content"])
        for i in items
        for e in expect
    )
    return full_hit, kind_hit


async def main() -> int:
    gate = "--gate" in sys.argv
    settings = get_settings()
    if not settings.zhipu_api_key:
        print("SKIP: 未配置 ZHIPU_API_KEY，跳过长期记忆评估回归门")
        return 0
    items = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    provider = ZhipuProvider(model=settings.model_light)

    rows: list[dict] = []
    for it in items:
        raw_out = ""
        extracted: list[dict] = []
        parse_ok = False
        try:
            raw_out = await provider.generate(
                [
                    {"role": "system", "content": _EXTRACT_SYSTEM_INSTRUCTION},
                    {"role": "user", "content": it["text"]},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            parse_ok = _extract_json(raw_out) is not None
            extracted = parse_memory_json(raw_out)
        except Exception as exc:  # noqa: BLE001
            raw_out = f"<调用异常: {exc}>"
        hit, kind_hit = _judge(it["expect"], extracted)
        rows.append(
            {
                "id": it["id"],
                "text": it["text"],
                "expect": it["expect"],
                "extracted": extracted,
                "parse_ok": parse_ok,
                "hit": hit,
                "kind_hit": kind_hit,
                "note": it.get("note", ""),
            }
        )

    total = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    parse_ok_n = sum(1 for r in rows if r["parse_ok"])
    pos = [r for r in rows if r["expect"]]
    adv = [r for r in rows if not r["expect"]]
    pos_kind = sum(1 for r in pos if r["kind_hit"])
    adv_pass = sum(1 for r in adv if r["hit"])

    def _expect_str(r: dict) -> str:
        if not r["expect"]:
            return "空（不抽取）"
        return " / ".join(f"{KIND_ZH.get(e['kind'], e['kind'])}·{e.get('keyword', '')}" for e in r["expect"])

    def _extracted_str(r: dict) -> str:
        if not r["extracted"]:
            return "空"
        return " / ".join(f"{KIND_ZH.get(i['kind'], i['kind'])}·{i['content']}" for i in r["extracted"])

    lines = [
        "# 长期记忆抽取稳定性评估（V6，E1 回归门）",
        "",
        f"- 测量时间：{settings.env} 环境 · 轻量模型 `{settings.model_light}` · temperature 0.2 · 线上同一抽取指令与解析器",
        f"- 评估集：`backend/scripts/eval-data/memory_eval_v1.json`，共 {total} 条（正向 {len(pos)} + 对抗 {len(adv)}）",
        f"- 综合命中率：**{hits}/{total} = {hits / total:.1%}**（go/no-go 阈值 ≥ 80%；正向命中 kind+关键词，对抗输出空）",
        f"- 输出可解析率（字段合法）：{parse_ok_n}/{total} = {parse_ok_n / total:.1%}",
        f"- 类别正确率（仅正向 {len(pos)} 条，辅助口径）：{pos_kind}/{len(pos)} = {pos_kind / len(pos):.1%}",
        f"- 对抗通过：{adv_pass}/{len(adv)} = {adv_pass / len(adv):.1%}",
        "",
        "## 明细",
        "",
        "| id | 文本 | 期望 | 实际抽取 | 命中 | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = "✓" if r["hit"] else "✗"
        lines.append(
            f"| {r['id']} | {r['text']} | {_expect_str(r)} | {_extracted_str(r)} | {mark} | {r['note']} |"
        )
    lines += [
        "",
        "## 结论",
        "",
        f"- 综合命中率 {hits / total:.1%}（{'达标' if hits / total >= HIT_THRESHOLD else '未达标'}，阈值 ≥ 80%）。",
        "- 对抗样本（一次性情绪/危机/闲聊/琐事/反讽/他人事件）跟踪「不该抽时不抽」的克制能力；",
        "  线上 bad-case 按 docs/eval-gate.md §4 回灌本评估集，形成「发现 → 固化 → 回归」闭环。",
    ]

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"综合命中率：{hits}/{total} = {hits / total:.1%}")
    print(f"输出可解析率：{parse_ok_n}/{total} = {parse_ok_n / total:.1%}")
    print(f"类别正确率（正向）：{pos_kind}/{len(pos)} = {pos_kind / len(pos):.1%}")
    print(f"报告已写入：{REPORT_FILE}")
    if gate:
        ratio = hits / total
        if ratio < HIT_THRESHOLD:
            print(f"GATE FAIL: 综合命中率 {ratio:.1%} < 阈值 {HIT_THRESHOLD:.0%}")
            return 1
        print(f"GATE PASS: 综合命中率 {ratio:.1%} >= 阈值 {HIT_THRESHOLD:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
