"""输出侧合规过滤（H）：对助手回复做确定性规则拦截。

红线（对齐 review-package / 非医疗定位）：
- 不得给出**诊断结论**（「你就是抑郁症」）；
- 不得**推荐药物**或指导用药（「建议吃舍曲林」「可以自行加量」）；
- 不得宣称**疗效**（「一定能治好」「根治」「一次见效」）。

实现为纯规则（正则 + 分句），不依赖模型自觉；命中后丢弃违规句并替换为
固定安全话术，日志只记类别不记原文。流式场景用 `OutputGuard` 按句缓冲，
保证跨 chunk 的违规句也能被完整识别。
"""
from __future__ import annotations

import re

# 违规句替换话术（短句，避免进一步给出任何建议性结论）
SAFE_TEXT: dict[str, str] = {
    "diagnosis": "我不能给出诊断，具体需要专业医生评估。",
    "medication": "用药请一定听专业医生的，不要自行加量或停药。",
    "efficacy": "我没法保证效果，具体进展需要专业评估。",
}

_DISORDERS = (
    "抑郁症|焦虑症|双相情感障碍|双相障碍|躁郁症|强迫症|精神分裂症|精神分裂|"
    "创伤后应激障碍|PTSD|进食障碍|人格障碍|多动症|ADHD|自闭症"
)

_DRUGS = (
    "舍曲林|氟西汀|帕罗西汀|氟伏沙明|艾司西酞普兰|西酞普兰|文拉法辛|度洛西汀|"
    "米氮平|曲唑酮|丁螺环酮|劳拉西泮|阿普唑仑|氯硝西泮|奥氮平|喹硫平|"
    "丙戊酸钠|碳酸锂|唑吡坦|右佐匹克隆|安眠药|褪黑素|抗抑郁药|抗焦虑药|镇静剂"
)

_DIAGNOSIS = re.compile(
    rf"((你|您|ta|他|她)(这|那)?(就是|属于|患有|患了|得了|确诊为|诊断为|是))"
    rf"[^，。！？\n]{{0,6}}({_DISORDERS})"
    rf"|((确诊|诊断)(结果)?(为|是)?)[^，。！？\n]{{0,4}}({_DISORDERS})"
    rf"|((你的|您的|ta的)(症状|情况|表现)(符合|是|说明|表明))"
    rf"[^，。！？\n]{{0,10}}({_DISORDERS})",
    re.IGNORECASE,
)

_MEDICATION = re.compile(
    rf"({_DRUGS})"
    r"|((建议|可以|不妨|试试|推荐|最好)[^，。！？\n]{0,6}(吃|服用|用)(点|一些)?(药))"
    r"|(加量|减量|停药|换药|加大剂量|减少剂量|调整剂量)"
)

_EFFICACY = re.compile(
    r"(一定|肯定|保证|绝对|百分百|100%|包)(能|会|可以)?"
    r"(治好|治愈|康复|痊愈|好起来|见效)"
    r"|(根治|包治|药到病除|立竿见影|一次见效|治愈率|彻底治愈|永不复发)"
    r"|(几天|一周|两周|一个月|很快|马上)(就|就能|就会|即可)(好|痊愈|康复|见效)"
)

# 分句但保留分隔符，便于按句替换
_SENTENCE_RE = re.compile(r"(?<=[。！？!?\n])")

# 流式缓冲上限：超长且无句末标点时强制放行，避免回复被无限延迟
_MAX_BUFFER = 200


def detect(sentence: str) -> str | None:
    """返回该句命中的违规类别（diagnosis/medication/efficacy），未命中返回 None。"""
    if _DIAGNOSIS.search(sentence):
        return "diagnosis"
    if _MEDICATION.search(sentence):
        return "medication"
    if _EFFICACY.search(sentence):
        return "efficacy"
    return None


def sanitize(text: str) -> tuple[str, list[str]]:
    """按句过滤整段回复：违规句替换为安全话术，返回 (安全文本, 命中类别列表)。"""
    if not text:
        return text, []
    hits: list[str] = []
    inserted: set[str] = set()
    out: list[str] = []
    for part in _SENTENCE_RE.split(text):
        category = detect(part)
        if category is None:
            out.append(part)
            continue
        if category not in hits:
            hits.append(category)
        # 同类违规话术只插入一次，避免安全提示刷屏
        if category not in inserted:
            inserted.add(category)
            out.append(SAFE_TEXT[category])
    return "".join(out), hits


class OutputGuard:
    """流式输出的合规守卫：按句缓冲，feed/flush 返回已可安全下发的内容。"""

    def __init__(self) -> None:
        self._buf = ""
        self.hits: list[str] = []

    def feed(self, delta: str) -> str:
        """追加增量；凑满整句时返回过滤后的文本，否则返回空串继续缓冲。"""
        self._buf += delta
        cut = 0
        for match in re.finditer(r"[。！？!?\n]", self._buf):
            cut = match.end()
        if not cut and len(self._buf) >= _MAX_BUFFER:
            cut = len(self._buf)
        if not cut:
            return ""
        ready, self._buf = self._buf[:cut], self._buf[cut:]
        safe, hits = sanitize(ready)
        self.hits.extend(hits)
        return safe

    def flush(self) -> str:
        """收尾：把剩余不完整句一并过滤后返回。"""
        if not self._buf:
            return ""
        ready, self._buf = self._buf, ""
        safe, hits = sanitize(ready)
        self.hits.extend(hits)
        return safe
