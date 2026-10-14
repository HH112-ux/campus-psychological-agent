"""P5 扩充评估集：v1(45条) + 强度黄金标注 + 12 条新样本（常规6+对抗6）→ emotion_eval_v2.json（57条）。"""
import json
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parent / "eval_data" / "emotion_eval_v1.json"
DST = Path(__file__).resolve().parent / "eval_data" / "emotion_eval_v2.json"

# 现有 45 条的金标准强度（1-10，专家标注）
INTENSITY = {
    "ax-01": 8, "ax-02": 7, "ax-03": 8, "ax-04": 7, "ax-05": 8,
    "ax-06": 7, "ax-07": 7, "ax-08": 8, "ax-09": 8, "ax-10": 7,
    "dp-01": 7, "dp-02": 9, "dp-03": 8, "dp-04": 7, "dp-05": 6,
    "dp-06": 7, "dp-07": 7, "dp-08": 7, "dp-09": 7, "dp-10": 7,
    "ok-01": 3, "ok-02": 4, "ok-03": 2, "ok-04": 4, "ok-05": 4,
    "ok-06": 2, "ok-07": 3, "ok-08": 4, "ok-09": 4, "ok-10": 4,
    "ag-01": 8, "ag-02": 8, "ag-03": 7, "ag-04": 7, "ag-05": 7,
    "ag-06": 8, "ag-07": 7, "ag-08": 7, "ag-09": 9, "ag-10": 8,
    "adv-01": 7, "adv-02": 7, "adv-03": 5, "adv-04": 2, "adv-05": 6,
}

NEW = [
    # 常规样本补齐（每类 +2 左右，保持四类均衡）
    {"id": "ax-11", "text": "明天就要汇报了，稿子改了三版还是觉得不行", "label": "anxious", "intensity": 7},
    {"id": "ax-12", "text": "考研成绩快出了，每天刷手机等消息，心慌", "label": "anxious", "intensity": 8},
    {"id": "dp-11", "text": "不知道从什么时候起，对什么都提不起兴趣了", "label": "depressed", "intensity": 7},
    {"id": "dp-12", "text": "日子一天天重复，感觉不到任何盼头", "label": "depressed", "intensity": 7},
    {"id": "ok-11", "text": "午休后醒来看窗外阳光正好，心情不错", "label": "calm", "intensity": 3},
    {"id": "ok-12", "text": "晚饭后散步半小时，整个人很放松", "label": "calm", "intensity": 2},
    {"id": "ag-11", "text": "投票结果出来我被莫名投出，真的很不服气", "label": "angry", "intensity": 7},
    {"id": "ag-12", "text": "新换的宿舍空调是坏的，报修三天没人理", "label": "angry", "intensity": 6},
    # 对抗样本补齐（反讽/引用/转述/嘴硬，目标 ≥10 条）
    {"id": "adv-06", "text": "真棒，又挂科了，我可太优秀了", "label": "depressed", "intensity": 7},
    {"id": "adv-07", "text": "他说人生总有起起落落，我听了点点头", "label": "calm", "intensity": 2},
    {"id": "adv-08", "text": "我朋友说最近压力大很焦虑，我也不知道怎么帮他", "label": "calm", "intensity": 2},
    {"id": "adv-09", "text": "没事的，我真的没事，你们别担心我了", "label": "depressed", "intensity": 7},
    {"id": "adv-10", "text": "我哪里会难过，我开心得很", "label": "depressed", "intensity": 6},
    {"id": "adv-11", "text": "今天只是普普通通的一天，平静得很", "label": "calm", "intensity": 2},
]

v1 = json.loads(SRC.read_text(encoding="utf-8"))
out = []
for it in v1:
    out.append({
        "id": it["id"],
        "text": it["text"],
        "label": it["label"],
        "intensity": INTENSITY[it["id"]],
        "note": it.get("note", ""),
    })
for it in NEW:
    out.append(it)

assert len(out) >= 50
adv = [i for i in out if i["id"].startswith("adv-")]
assert len(adv) >= 10
print("总条数:", len(out), "| 对抗:", len(adv), "| 按类:", dict(Counter(i["label"] for i in out)))
DST.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("written:", DST)
