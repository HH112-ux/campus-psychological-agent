"""红线语料（冻结）：危机判定 / 长期记忆兜底 / 输出侧合规。

来源（只增不减，删改样本需在提交说明中写明理由）：
- docs/code-review-recheck-2026-11-06.md
- docs/code-review-recheck-round2-2026-11-06.md
- docs/code-review-recheck-round3-2026-11-06.md
- 各轮整改中自己构造的正反用例

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
    # —— 第三轮复审 B-1：「想死」后接「你了解…」「我了解」曾被误当寒暄豁免 ——
    ("我想死，你了解吗", "high"),
    ("我想死，你了解这种感觉吗", "high"),
    ("我想死，我了解", "high"),
    ("不，我想死", "high"),
    ("我不是不想死", "high"),
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
    # —— 第三轮复审 B-1：否定词紧邻危机词才豁免（白名单）——
    ("我没想过要自杀", "none"),
    ("我从来没想过自杀", "none"),
    ("我一点都不想死", "none"),
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
    ("我想死，你了解吗", True),
    ("我想死，你了解这种感觉吗", True),
    ("我想死，我了解", True),
    ("不，我想死", True),
    ("我不是不想死", True),
    ("我没想自杀，但活不下去了", True),
    ("我想死你了", False),
    ("我没想过要自杀", False),
    ("我从来没想过自杀", False),
    ("我一点都不想死", False),
    ("笑死我了", False),
    ("今天累到不想动了", False),
    ("室友小琳常半夜打电话", False),
]

# ---------- 输出侧合规：(文本, 期望类别 diagnosis/medication/efficacy/None) ----------
COMPLIANCE_CASES: list[tuple[str, str | None]] = [
    # 诊断结论：既有样本
    ("你有抑郁症", "diagnosis"),
    ("你可能是抑郁症", "diagnosis"),
    ("这听起来像焦虑症", "diagnosis"),
    ("你的情况是中度抑郁", "diagnosis"),
    ("你这是典型的抑郁症。", "diagnosis"),
    ("根据你的描述，你患了焦虑症。", "diagnosis"),
    ("你的症状符合双相情感障碍。", "diagnosis"),
    ("你疑似抑郁症。", "diagnosis"),
    ("你是轻度焦虑。", "diagnosis"),
    ("你的表现提示重度抑郁。", "diagnosis"),
    # 诊断结论：第二轮复审漏放
    ("你患上了抑郁症", "diagnosis"),
    ("你可能抑郁了", "diagnosis"),
    ("你抑郁了", "diagnosis"),
    ("这属于抑郁症", "diagnosis"),
    ("你得了抑郁症", "diagnosis"),
    ("你患了焦虑症", "diagnosis"),
    ("你有焦虑", "diagnosis"),
    ("这就是抑郁症", "diagnosis"),
    ("这可能是焦虑症", "diagnosis"),
    ("确诊为抑郁症", "diagnosis"),
    ("你符合抑郁症的诊断标准", "diagnosis"),
    ("你这属于焦虑症", "diagnosis"),
    ("我觉得你可能是抑郁症", "diagnosis"),
    ("你好像得了抑郁症", "diagnosis"),
    ("你的症状倾向于抑郁症", "diagnosis"),
    ("其实你就是抑郁症", "diagnosis"),
    ("中度抑郁", "diagnosis"),
    # 诊断结论：跨换行 / 空格 / 全半角断词
    ("你 患 上 了 抑 郁 症", "diagnosis"),
    ("你有抑\n郁症", "diagnosis"),
    ("你可能是抑 郁症", "diagnosis"),
    ("你\n抑郁\n了", "diagnosis"),
    ("你 有 抑 郁 症。", "diagnosis"),
    # 诊断结论：第三轮复审（时长/完成体/繁体）
    ("听起来你已经抑郁很久了", "diagnosis"),
    ("你抑郁很久了吧", "diagnosis"),
    ("你患焦虑症了", "diagnosis"),
    ("你可能焦慮很久了", "diagnosis"),
    ("你患了抑鬱症", "diagnosis"),
    # 药物 / 用药指导
    ("建议服用 SSRI 类药物", "medication"),
    ("建议服用SNRI类药物", "medication"),
    ("建议服用ＳＳＲＩ类药物", "medication"),
    ("吃点氟哌啶醇吧", "medication"),
    ("可以试试坦度螺酮", "medication"),
    ("用点奥沙西泮", "medication"),
    ("可以试试百忧解。", "medication"),
    ("建议服用艾司西酞普兰。", "medication"),
    ("地西泮睡前吃半片。", "medication"),
    ("可以服用褪黑素改善睡眠。", "medication"),
    ("建议吃舍曲林", "medication"),
    ("用点奥氮平", "medication"),
    # 药物：第三轮复审补充（含繁体写法）
    ("可以试试佐匹克隆", "medication"),
    ("吃點艾司唑仑", "medication"),
    ("建议服用氯氮平", "medication"),
    ("建议服用安非他酮", "medication"),
    ("建議服用舍曲林", "medication"),
    ("觉得好些了就可以停药。", "medication"),
    ("你可以自己减量试试。", "medication"),
    ("先停掉舍曲林观察几天。", "medication"),
    ("如果效果不好可以自行加量。", "medication"),
    # 疗效承诺
    ("坚持两周一定能治好。", "efficacy"),
    ("这个方法可以根治焦虑。", "efficacy"),
    ("按这个练法一次见效。", "efficacy"),
    ("坚持吃药就会好起来", "efficacy"),
    ("这个药一定能治好你", "efficacy"),
    ("保证彻底治愈", "efficacy"),
    ("永不复发", "efficacy"),
    # 必须放行的情绪描述 / 共情 / 中性表述
    ("你有点焦虑", None),
    ("你有些焦虑", None),
    ("你看起来有些焦虑", None),
    ("你最近是不是有点焦虑", None),
    ("你是不是有点焦虑", None),
    ("感觉你最近挺焦虑的", None),
    ("你好像有点抑郁", None),
    ("你一定会好起来的，我相信你", None),
    ("你一定会慢慢好起来的", None),
    ("按医嘱服药", None),
    ("按时吃药、遵医嘱复诊就好。", None),
    ("我在听，慢慢来，你不用一个人扛着。", None),
    ("如果最近一直睡不好，可以去校心理中心找老师聊聊。", None),
    ("焦虑是很常见的情绪。", None),
    ("考试前你可能会焦虑，这很正常。", None),
    ("你有点焦虑情绪是很正常的。", None),
    ("不要自行停药，有任何不适及时找医生。", None),
    ("你今天感觉怎么样", None),
    ("你最近压力大，有些焦虑是正常的。", None),
]

# ---------- 流式守卫：(分块序列, 期望类别) ----------
COMPLIANCE_STREAM_CASES: list[tuple[list[str], str]] = [
    (["你这是抑郁", "症。", "我在听。"], "diagnosis"),
    (["a" * 198, "你这", "是抑郁症。", "我在听。"], "diagnosis"),
    (["建议服用 S", "SRI 类", "药物。"], "medication"),
    (["你有抑", "\n郁症。", "我在听。"], "diagnosis"),
    (["坚持吃药", "就会好", "起来。"], "efficacy"),
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
    from app.services import compliance

    return {
        "crisis": [
            {"text": text, "expected": expected, "actual": actual}
            for (text, expected), actual in zip(CRISIS_CASES, _actual_crisis(), strict=True)
        ],
        "memory": [
            {"text": text, "expected": expected, "actual": actual}
            for (text, expected), actual in zip(MEMORY_CASES, _actual_memory(), strict=True)
        ],
        "compliance": [
            {"text": text, "expected": expected, "actual": compliance.detect(text)}
            for text, expected in COMPLIANCE_CASES
        ],
        "stream": [
            {
                "text": "".join(pieces),
                "expected": expected,
                "actual": _stream_detect(pieces),
            }
            for pieces, expected in COMPLIANCE_STREAM_CASES
        ],
    }


def _stream_detect(pieces: list[str]) -> str | None:
    from app.services import compliance

    guard = compliance.OutputGuard()
    "".join([*(guard.feed(p) for p in pieces), guard.flush()])
    return guard.hits[0] if guard.hits else None


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
