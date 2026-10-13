"""M3 情绪分类一致率首次测量（验收留档）。

用法（在 backend/ 目录下运行，需 .env 中的 ZHIPU_API_KEY）：
    DYLD_FRAMEWORK_PATH=... DYLD_LIBRARY_PATH=... .venv/bin/python scripts/eval_emotion.py

- 评估集：scripts/eval_data/emotion_eval_v1.json（四类各 10 条 + 5 条对抗样本）
- 调用链路与线上一致：轻量模型 glm-4-flash、temperature 0.2、同一系统指令与解析器
- 指标：总一致率、按类一致率、对抗样本一致率；结果写入 docs/emotion-eval-m3.md
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.llm.zhipu import ZhipuProvider  # noqa: E402
from app.services.emotion import _EMOTION_SYSTEM_INSTRUCTION, parse_emotion_json  # noqa: E402

EVAL_FILE = Path(__file__).resolve().parent / "eval_data" / "emotion_eval_v1.json"
REPORT_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "emotion-eval-m3.md"
)
LABEL_ZH = {
    "anxious": "焦虑",
    "depressed": "低落/抑郁",
    "calm": "平静/良好",
    "angry": "愤怒/烦躁",
}


async def main() -> int:
    settings = get_settings()
    items = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    provider = ZhipuProvider(model=settings.model_light)

    rows: list[dict] = []
    for it in items:
        messages = [
            {"role": "system", "content": _EMOTION_SYSTEM_INSTRUCTION},
            {"role": "user", "content": it["text"]},
        ]
        predicted = None
        raw_out = ""
        try:
            raw_out = await provider.generate(
                messages, temperature=0.2, max_tokens=200
            )
            analysis = parse_emotion_json(raw_out)
            predicted = analysis.emotion if analysis else None
        except Exception as exc:  # noqa: BLE001
            raw_out = f"<调用异常: {exc}>"
        rows.append(
            {
                "id": it["id"],
                "text": it["text"],
                "gold": it["label"],
                "pred": predicted,
                "ok": predicted == it["label"],
                "note": it.get("note", ""),
                "raw": raw_out,
            }
        )

    total = len(rows)
    correct = sum(1 for r in rows if r["ok"])
    by_class: dict[str, list] = {}
    for r in rows:
        by_class.setdefault(r["gold"], []).append(r)
    adv = [r for r in rows if r["id"].startswith("adv-")]

    lines = [
        "# 情绪分类一致率测量（M3 首次留档）",
        "",
        f"- 测量时间：{settings.env} 环境 · 轻量模型 `{settings.model_light}` · temperature 0.2",
        f"- 评估集：`backend/scripts/eval_data/emotion_eval_v1.json`，共 {total} 条"
        "（四类各 10 条 + 5 条反讽/引用对抗样本）",
        f"- 总一致率：**{correct}/{total} = {correct / total:.1%}**（目标 ≥ 80%，P5 达标线）",
        "",
        "## 按类一致率",
        "",
        "| 类别 | 样本数 | 一致数 | 一致率 |",
        "|---|---|---|---|",
    ]
    for cls in ("anxious", "depressed", "calm", "angry"):
        recs = by_class.get(cls, [])
        c = sum(1 for r in recs if r["ok"])
        lines.append(
            f"| {LABEL_ZH[cls]}（{cls}） | {len(recs)} | {c} | {c / len(recs):.1%} |"
        )
    adv_c = sum(1 for r in adv if r["ok"])
    lines += [
        f"| 对抗样本（反讽/引用） | {len(adv)} | {adv_c} | {adv_c / len(adv):.1%} |",
        "",
        "## 预测分布",
        "",
        "| 黄金标签 \\ 预测 | " + " | ".join(LABEL_ZH.get(c, c) for c in ("anxious", "depressed", "calm", "angry", "other", "None")) + " |",
        "|---|" + "---|" * 5,
    ]
    pred_order = ("anxious", "depressed", "calm", "angry", "other", "None")
    for cls in ("anxious", "depressed", "calm", "angry"):
        recs = by_class.get(cls, [])
        cnt = Counter(r["pred"] if r["pred"] else "None" for r in recs)
        cells = [str(cnt.get(p, 0)) for p in pred_order]
        lines.append(f"| {LABEL_ZH[cls]}（{cls}） | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 不一致明细（M3 基线，供提示词/词库迭代参考）",
        "",
        "| id | 文本 | 黄金 | 预测 | 备注 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if not r["ok"]:
            lines.append(
                f"| {r['id']} | {r['text']} | {LABEL_ZH.get(r['gold'], r['gold'])} "
                f"| {r['pred'] or '解析失败'} | {r['note']} |"
            )
    lines += [
        "",
        "## 说明",
        "",
        "- 单条样本为单轮评估（不含上下文）；线上为「本轮消息 + 前两轮上下文」，一致率可能略高。",
        "- 强度平均误差（≤2 目标）需要黄金强度标注，P5 扩充评估集时一并补齐。",
        "- 本报告为 M3 首次测量留档；P5 将扩充至 ≥50 条（对抗样本 ≥10 条）并作为 go/no-go 依据。",
    ]

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"总一致率：{correct}/{total} = {correct / total:.1%}")
    print(f"报告已写入：{REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
