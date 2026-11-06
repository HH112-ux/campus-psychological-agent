"""输出侧合规过滤（H）：对助手回复做确定性规则拦截。

红线（对齐 review-package / 非医疗定位）：
- 不得给出**诊断结论**（「你就是抑郁症」「你可能是抑郁症」「你的情况是中度抑郁」）；
- 不得**推荐药物**或指导用药（「可以试试百忧解」「建议吃舍曲林」「自行加量」）；
- 不得宣称**疗效**（「一定能治好」「根治」「一次见效」）。

实现为纯规则（正则 + 分句），不依赖模型自觉；命中后丢弃违规句并替换为
固定安全话术，日志只记类别不记原文。

流式场景（`OutputGuard`）的关键约束：违规句可能被拆在多个 chunk 里，
因此**任何已经下发的文本都不能再与后续文本拼成违规句**。做法是只在句末
标点处切分；若模型长时间不给标点，则保留末尾 `_HOLD_BACK` 个字符不发送，
只下发此前部分。`_HOLD_BACK` 大于任一规则的最大匹配跨度，因此跨切点的
违规句必然整体落在保留区，等切分点出现（或 flush）时再整体判定。
"""
from __future__ import annotations

import re

# 违规句替换话术（短句，避免进一步给出任何建议性结论）
SAFE_TEXT: dict[str, str] = {
    "diagnosis": "我不能给出诊断，具体需要专业医生评估。",
    "medication": "用药请一定听专业医生的，不要自行加量或停药。",
    "efficacy": "我没法保证效果，具体进展需要专业评估。",
}

# 精神科常见诊断名（明确病名）
_DISORDERS = (
    "抑郁症|焦虑症|双相情感障碍|双相障碍|躁郁症|强迫症|精神分裂症|精神分裂|"
    "创伤后应激障碍|PTSD|进食障碍|人格障碍|多动症|ADHD|自闭症|"
    "惊恐障碍|社交恐惧症|社交焦虑障碍|躯体化障碍|疑病症|失眠症"
)
# 裸病名：只在出现判断/分度语境时才算诊断结论，避免误伤「焦虑的情绪很正常」
_BARE = "抑郁|焦虑"

# 分度/倾向词（轻中度、疑似…）
_SEVERITY = (
    r"(?:(?:轻|中|重)度|轻中度|疑似|偏重|倾向(?:于)?|可能是|也许是|疑似患有)"
)
# 强判断动词：直接下结论
_ASSERTIVE = r"(?:就是|属于|患有|患了|得了|确诊为|诊断为|符合|典型(?:的)?|确诊|诊断)"
# 弱判断动词：仍需跟明确病名（或有分度词）
_WEAK = r"(?:可能|也许|大概|似乎|听起来像|看起来像|像是|像|疑似|是|有)"
# 纯粹的表判断/存在（与裸病名相邻时才判定）
_COPULA = r"(?:是|有)"
# 推断词（与裸病名同现时必须带分度词，否则「考试前你可能会焦虑」会被误伤）
_INFER = r"(?:可能|也许|大概|似乎|听起来|看起来|像是|像|疑似)"
_PERSON = r"(?:你|您|ta|他|她)"
_OWNER = r"(?:的(?:情况|症状|表现|状态|问题))?"

_DIAGNOSIS = re.compile(
    # 1) 第二人称 + 强判断动词 + 病名（含裸病名）
    rf"{_PERSON}{_OWNER}[^，。！？\n]{{0,8}}?{_ASSERTIVE}"
    rf"[^，。！？\n]{{0,6}}?{_SEVERITY}?(?:{_DISORDERS}|{_BARE})"
    # 2) 第二人称 + 弱判断动词 + 明确病名
    rf"|{_PERSON}{_OWNER}[^，。！？\n]{{0,8}}?{_WEAK}"
    rf"[^，。！？\n]{{0,6}}?{_SEVERITY}?(?:{_DISORDERS})"
    # 3) 第二人称 + 是/有 + 裸病名（「你是抑郁」「你有焦虑」，间隔 ≤2）
    #    「你有点焦虑情绪」属正常化共情，不算诊断结论
    rf"|{_PERSON}{_OWNER}[^，。！？\n]{{0,8}}?{_COPULA}"
    rf"[^，。！？\n]{{0,2}}?{_SEVERITY}?(?:{_BARE})(?!情绪|感受|心情)"
    # 4) 第二人称 + 推断词 + 分度 + 裸病名（「你可能是中度抑郁」）
    rf"|{_PERSON}{_OWNER}[^，。！？\n]{{0,8}}?{_INFER}"
    rf"[^，。！？\n]{{0,4}}?{_SEVERITY}(?:{_BARE})"
    # 5) 无主语：「这听起来像焦虑症」
    rf"|(?:这|那|这个|这种情况|你的情况)?(?:听起来|看起来|感觉|似乎)"
    rf"(?:像|像是|是|属于)?[^，。！？\n]{{0,6}}?{_SEVERITY}?(?:{_DISORDERS}|{_BARE})"
    # 6) 病情判断句：「你的症状符合双相情感障碍」
    rf"|(?:你的|您的|ta的|他的|她的|其)(?:症状|情况|表现|状态)"
    rf"[^，。！？\n]{{0,10}}?(?:符合|可能是|是|说明|表明|提示|倾向于)"
    rf"[^，。！？\n]{{0,6}}?{_SEVERITY}?(?:{_DISORDERS}|{_BARE})"
    # 7) 确诊/诊断：「确诊为抑郁症」
    rf"|(?:确诊|诊断)(?:结果)?(?:为|是)?[^，。！？\n]{{0,6}}?{_SEVERITY}?(?:{_DISORDERS}|{_BARE})"
    # 8) 单纯分度前缀：「中度抑郁」
    rf"|(?:轻度|中度|重度|轻中度)(?:{_DISORDERS}|{_BARE})",
    re.IGNORECASE,
)

_DRUGS = (
    # 通用名
    "舍曲林|氟西汀|帕罗西汀|氟伏沙明|艾司西酞普兰|西酞普兰|文拉法辛|度洛西汀|"
    "米氮平|曲唑酮|丁螺环酮|劳拉西泮|阿普唑仑|氯硝西泮|地西泮|奥氮平|喹硫平|"
    "丙戊酸钠|碳酸锂|唑吡坦|右佐匹克隆|阿米替林|多塞平|氯米帕明|舍曲林片|"
    # 常见商品名（患者/模型更常说品牌名）
    "百忧解|左洛复|来士普|赛乐特|怡诺思|欣百达|瑞美隆|思诺思|黛力新|"
    "舒乐安定|佳静安定|安定片|阿普唑仑片|米安色林|曲舍林"
    # 品类
    "|安眠药|褪黑素|抗抑郁药|抗焦虑药|镇静剂|抗精神病药"
)
_DRUGS_RE = re.compile(rf"({_DRUGS})", re.IGNORECASE)

# 停药/减药/自行调整剂量：属于「用药指导」，无论是否推荐具体药名都拦截
_STOP_ADVICE_RE = re.compile(
    r"(?:停药|减药|减量|停掉|断药|断了药|不用吃了|可以停|自行停|"
    r"减少剂量|加大剂量|调整剂量|换药|加量)"
)
# 否定/遵医嘱语境：同一分句内出现即视为安全叮嘱，不拦截
_NEGATION_RE = re.compile(r"(?:不要|不能|不可|别|勿|切勿|避免|禁止|不建议|遵医嘱|听医生|按医生)")
_CLAUSE_SPLIT_RE = re.compile(r"[，,；;。！？!?\n]")

_EFFICACY = re.compile(
    r"(一定|肯定|保证|绝对|百分百|100%|包)(能|会|可以)?"
    r"(治好|治愈|康复|痊愈|好起来|见效)"
    r"|(根治|包治|药到病除|立竿见影|一次见效|治愈率|彻底治愈|永不复发)"
    r"|(几天|一周|两周|一个月|很快|马上)(就|就能|就会|即可)(好|痊愈|康复|见效)"
)

# 分句但保留分隔符，便于按句替换
_SENTENCE_RE = re.compile(r"(?<=[。！？!?\n])")

# 流式切分点：只在句末标点后切
_TERMINATOR_RE = re.compile(r"[。！？!?\n]")
# 无标点时的保留窗口：必须大于任一规则的最大匹配跨度，
# 否则一个违规句可能被切在「已下发」与「保留区」两侧（上一轮 200 字强制切分即此缺陷）。
_HOLD_BACK = 48


def _drug_or_advice_hit(sentence: str) -> bool:
    if _DRUGS_RE.search(sentence):
        return True
    for match in _STOP_ADVICE_RE.finditer(sentence):
        clause_start = 0
        for sep in _CLAUSE_SPLIT_RE.finditer(sentence[: match.start()]):
            clause_start = sep.end()
        clause = sentence[clause_start : match.end()]
        if not _NEGATION_RE.search(clause):
            return True
    return False


def detect(sentence: str) -> str | None:
    """返回该句命中的违规类别（diagnosis/medication/efficacy），未命中返回 None。"""
    if _DIAGNOSIS.search(sentence):
        return "diagnosis"
    if _drug_or_advice_hit(sentence):
        return "medication"
    if _EFFICACY.search(sentence):
        return "efficacy"
    return None


def sanitize(
    text: str, inserted: set[str] | None = None
) -> tuple[str, list[str]]:
    """按句过滤整段回复：违规句替换为安全话术，返回 (安全文本, 命中类别列表)。

    `inserted` 由调用方传入可在多次调用间共享（流式守卫用它避免同类安全话术重复插入）。
    """
    if not text:
        return text, []
    hits: list[str] = []
    seen = inserted if inserted is not None else set()
    out: list[str] = []
    for part in _SENTENCE_RE.split(text):
        category = detect(part)
        if category is None:
            out.append(part)
            continue
        if category not in hits:
            hits.append(category)
        # 同类违规话术在同一条回复内只插入一次，避免安全提示刷屏
        if category not in seen:
            seen.add(category)
            out.append(SAFE_TEXT[category])
    return "".join(out), hits


class OutputGuard:
    """流式输出的合规守卫：按句缓冲，feed/flush 返回已可安全下发的内容。

    切分规则：
    1. 有句末标点：切到最后一个句末标点，整句判定后下发；
    2. 无句末标点：仅当缓冲超过 `_HOLD_BACK` 时，下发「缓冲长度 - _HOLD_BACK」的前缀，
       末 48 字保留到下一轮。保留窗大于规则最大匹配跨度，跨窗违规句因此仍会被整体判定。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._inserted: set[str] = set()
        self.hits: list[str] = []

    def feed(self, delta: str) -> str:
        """追加增量；有可安全下发的部分时返回过滤后的文本，否则返回空串。"""
        self._buf += delta
        cut = 0
        for match in _TERMINATOR_RE.finditer(self._buf):
            cut = match.end()
        if not cut and len(self._buf) > _HOLD_BACK:
            cut = len(self._buf) - _HOLD_BACK
        if not cut:
            return ""
        ready, self._buf = self._buf[:cut], self._buf[cut:]
        safe, hits = sanitize(ready, inserted=self._inserted)
        self.hits.extend(hits)
        return safe

    def flush(self) -> str:
        """收尾：把剩余不完整句一并过滤后返回。"""
        if not self._buf:
            return ""
        ready, self._buf = self._buf, ""
        safe, hits = sanitize(ready, inserted=self._inserted)
        self.hits.extend(hits)
        return safe
