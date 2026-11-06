"""红线语料（冻结）：危机判定 / 长期记忆兜底。

来源（只增不减，删改样本需在提交说明中写明理由）：
- docs/code-review-recheck-2026-11-06.md
- docs/code-review-recheck-round2-2026-11-06.md
- 两轮整改中自己构造的正反用例

用途：
1. tests/test_redline_regression.py 逐条断言（常驻回归，第一道门）；
2. `python -m tests.redline_corpus` 输出当前代码的判定 JSON，
   用于「改前 / 改后 / 期望」行为差异表。
"""
from __future__ import annotations

import asyncio
import json

# ---------- 危机判定：(文本, 期望级别 none/mid/high) ----------
CRISIS_CASES: list[tuple[str, str]] = [
    # —— 第二轮复审 B-3 原样回归句（曾判 none，红线）——
    ("我想死，你能帮帮我吗", "high"),
    ("我想死，你说我该怎么办", "high"),
    ("我想死，你要好好的", "high"),
    ("我想死，你们别管我", "high"),
    # —— 真实危机 + 疑问/求助语气 ——
    ("我想死，怎么办", "high"),
    ("不想活了，你能听我说吗", "high"),
    ("我真的不想活了，你能帮帮我吗", "high"),
    ("我想自杀，你能劝劝我吗", "high"),
    ("我不想活了，有人能听我说说话吗", "high"),
    ("我想死，你能陪我聊聊吗", "high"),
    # —— 一级强信号 ——
    ("我想死", "high"),
    ("我不想活了", "high"),
    ("我想自杀", "high"),
    ("我想跳楼", "high"),
    ("我要割腕", "high"),
    ("我准备吃安眠药一了百了", "high"),
    ("想结束自己的生命", "high"),
    ("我想了结自己", "high"),
    ("我 不 想 活 了", "high"),
    ("不.想.活了，好累", "high"),
    ("我zisha算了", "high"),
    ("wosi", "high"),
    ("buxianghuole", "high"),
    ("zican", "high"),
    ("gewan", "high"),
    ("tiaolou", "high"),
    ("紫砂了吧", "high"),
    ("我想杀人", "high"),
    ("想报复社会", "high"),
    ("我想和他同归于尽", "high"),
    ("弄死他就好了", "high"),
    ("我想掐死她", "high"),
    ("我要砍人", "high"),
    ("我不想死，但也不想活了", "high"),
    ("我没想自杀，但活不下去了", "high"),
    ("没人在乎我，活着好累", "high"),
    # —— 二级语境信号 ——
    ("最近真的撑不住了，太累了", "mid"),
    ("活着好累啊", "mid"),
    ("活着没意思", "mid"),
    ("真的撑不下去了", "mid"),
    ("没人在乎我", "mid"),
    ("我不想死，可是活着好累", "mid"),
    # —— 正常表达（不得判危机）——
    ("今天天气真好", "none"),
    ("这游戏真没意思", "none"),
    ("我要去食堂吃饭了", "none"),
    ("明天有一门期末考试", "none"),
    ("老师讲的课我有点听不明白", "none"),
    ("消息怎么突然消失了", "none"),
    ("今天累到不想动了", "none"),
    ("累了一天，不想动了", "none"),
    ("我不想死", "none"),
    ("我没想自杀", "none"),
    ("我想死你了", "none"),
    ("你真是想死我了", "none"),
    ("我想死您了", "none"),
    ("我热得要死了", "none"),
    ("笑死我了", "none"),
    ("今天累死我了", "none"),
    ("饿死我了", "none"),
    ("困死我了", "none"),
    ("吓死我了", "none"),
    ("忙死我了", "none"),
    ("烦死我了", "none"),
    ("热得要命", "none"),
    ("冷得要死", "none"),
    ("你真是笑死我了", "none"),
]

# ---------- 长期记忆确定性兜底：(文本, 是否应判为含危机内容) ----------
MEMORY_CASES: list[tuple[str, bool]] = [
    ("我想死，你能帮帮我吗", True),
    ("我想死，你们别管我", True),
    ("我不想活了，你能听我说吗", True),
    ("我想死", True),
    ("我没想自杀，但活不下去了", True),
    ("我想死你了", False),
    ("笑死我了", False),
    ("今天累到不想动了", False),
    ("室友小琳常半夜打电话", False),
]


def _actual_crisis() -> list[str]:
    from app.services import crisis

    async def _run():
        return [
            (await crisis.detect_risk(text, {"crisis_score": 0})).level
            for text, _ in CRISIS_CASES
        ]

    return asyncio.run(_run())


def _actual_memory() -> list[bool]:
    from app.services import crisis

    async def _run():
        return [bool(await crisis.contains_crisis_terms(text)) for text, _ in MEMORY_CASES]

    return asyncio.run(_run())


def collect() -> dict:
    """返回当前代码对全部语料的判定，供基线/差异对比。"""
    return {
        "crisis": [
            {"text": text, "expected": expected, "actual": actual}
            for (text, expected), actual in zip(CRISIS_CASES, _actual_crisis(), strict=True)
        ],
        "memory": [
            {"text": text, "expected": expected, "actual": actual}
            for (text, expected), actual in zip(MEMORY_CASES, _actual_memory(), strict=True)
        ],
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
