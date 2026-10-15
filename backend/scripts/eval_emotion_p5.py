"""P5 情绪分类一致率正式评估（go/no-go 依据，V2 提示词）。

用法（backend/ 目录，需 .env 中的 ZHIPU_API_KEY）：
    .venv/bin/python scripts/eval_emotion_p5.py

- 评估集：scripts/eval-data/emotion_eval_v2.json（59 条：四类 14/17/16/12 + 对抗 11）
- 链路与线上一致：glm-4-flash、temperature 0.2、同一系统指令（V2）与解析器
- 指标：严格一致率（≥80% 达标）、按类一致率、对抗一致率、强度 MAE（≤2 目标，
  仅对分类一致的样本计）、ok≈calm 近义归并（辅助口径，不计入主指标）
- 输出：docs/emotion-eval-p5.md
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

EVAL_FILE = Path(__file__).resolve().parent / "eval-data" / "emotion_eval_v2.json"
REPORT_FILE = Path(__file__).resolve().parents[2] / "docs" / "emotion-eval-p5.md"

LABEL_ZH = {
    "anxious": "焦虑",
    "depressed": "低落/抑郁",
    "calm": "平静/良好",
    "angry": "愤怒/烦躁",
    "ok": "还行",
    "other": "其他",
}
NEAR_SYN = {("calm", "ok"), ("ok", "calm")}  # 近义归并：平静≈还行


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
        pred_int = None
        raw_out = ""
        try:
            raw_out = await provider.generate(
                messages, temperature=0.2, max_tokens=200
            )
            analysis = parse_emotion_json(raw_out)
            if analysis:
                predicted = analysis.emotion
                pred_int = analysis.intensity
        except Exception as exc:  # noqa: BLE001
            raw_out = f"<调用异常: {exc}>"
        rows.append(
            {
                "id": it["id"],
                "text": it["text"],
                "gold": it["label"],
                "gold_int": it.get("intensity"),
                "pred": predicted,
                "pred_int": pred_int,
                "ok": predicted == it["label"],
                "near": (predicted, it["label"]) in NEAR_SYN,
                "note": it.get("note", ""),
                "raw": raw_out,
            }
        )

    total = len(rows)
    correct = sum(1 for r in rows if r["ok"])
    near_hits = sum(1 for r in rows if r["near"])

    # 强度误差：仅对分类一致的样本
    int_abs = [
        abs(r["gold_int"] - r["pred_int"])
        for r in rows
        if r["ok"] and r["gold_int"] is not None and r["pred_int"] is not None
    ]
    int_mae = sum(int_abs) / len(int_abs) if int_abs else None

    by_class: dict[str, list] = {}
    for r in rows:
        by_class.setdefault(r["gold"], []).append(r)
    adv = [r for r in rows if r["id"].startswith("adv-")]

    lines = [
        "# 情绪分类一致率正式评估（P5，go/no-go 依据）",
        "",
        f"- 测量时间：{settings.env} 环境 · 轻量模型 `{settings.model_light}` · temperature 0.2 · 提示词 V2",
        f"- 评估集：`backend/scripts/eval-data/emotion_eval_v2.json`，共 {total} 条"
        "（四类 14/17/16/12 + 对抗 11，含黄金强度标注）",
        f"- 严格总一致率：**{correct}/{total} = {correct / total:.1%}**（go/no-go 阈值 ≥ 80%）",
        f"- 近义归并辅助（ok≈calm，不计入主指标）：另计 {near_hits} 条",
        (
            f"- 强度平均绝对误差（分类一致样本，目标 ≤2）：**{int_mae:.2f}**"
            if int_mae is not None
            else "- 强度平均绝对误差：无法计算（无一致样本）"
        ),
        "",
        "## 按类一致率（严格）",
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
    adv_near = sum(1 for r in adv if r["near"])
    lines += [
        f"| 对抗样本（反讽/引用/转述） | {len(adv)} | {adv_c} | {adv_c / len(adv):.1%}"
        + (f"（含近义 {adv_near}） |" if adv_near else " |"),
        "",
        "## 预测分布（严格口径）",
        "",
        "| 黄金标签 \\ 预测 | " + " | ".join(LABEL_ZH.get(c, c) for c in ("anxious", "depressed", "calm", "ok", "angry", "other", "None")) + " |",
        "|---|" + "---|" * 6,
    ]
    pred_order = ("anxious", "depressed", "calm", "ok", "angry", "other", "None")
    for cls in ("anxious", "depressed", "calm", "angry"):
        recs = by_class.get(cls, [])
        cnt = Counter(r["pred"] if r["pred"] else "None" for r in recs)
        cells = [str(cnt.get(p, 0)) for p in pred_order]
        lines.append(f"| {LABEL_ZH[cls]}（{cls}） | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## 不一致明细（V2 基线，供继续迭代）",
        "",
        "| id | 文本 | 黄金 | 预测 | 备注 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if not r["ok"] and not r["near"]:
            lines.append(
                f"| {r['id']} | {r['text']} | {LABEL_ZH.get(r['gold'], r['gold'])} "
                f"| {r['pred'] or '解析失败'} | {r['note']} |"
            )
    lines += [
        "",
        "## 结论",
        "",
        f"- 严格一致率 {correct / total:.1%}（{'达标' if correct / total >= 0.8 else '未达标'}，阈值 ≥ 80%），"
        f"对抗样本 {adv_c}/{len(adv)}（{adv_c / len(adv):.1%}），强度 MAE {int_mae:.2f}（目标 ≤ 2）。",
        "- 近义归并后综合一致率："
        f"**{(correct + near_hits) / total:.1%}**（若将 calm≈ok 视为一致）。",
        "- 单条样本为单轮评估（不含上下文）；线上为「本轮消息 + 前两轮上下文」，一致率可能略高。",
    ]

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"严格一致率：{correct}/{total} = {correct / total:.1%}")
    print(f"近义归并后：{(correct + near_hits)}/{total} = {(correct + near_hits) / total:.1%}")
    print(f"强度 MAE：{int_mae:.2f}" if int_mae is not None else "强度 MAE：N/A")
    print(f"报告已写入：{REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
