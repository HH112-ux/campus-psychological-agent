"""输出侧合规过滤（H）：对助手回复做确定性规则拦截。

红线（对齐 review-package / 非医疗定位）：
- 不得给出**诊断结论**（「你就是抑郁症」「你可能是抑郁症」「这属于抑郁症」）；
- 不得**推荐药物**或指导用药（「可以试试百忧解」「建议服用 SSRI」「自行加量」）；
- 不得宣称**疗效**（「一定能治好」「坚持吃药就会好起来」「根治」）。

实现为纯规则（正则 + 分句），不依赖模型自觉；命中后丢弃违规句并替换为
固定安全话术，日志只记类别不记原文。

两条关键边界：
1. 「对用户情绪的描述」与「对用户下诊断结论」分开：`你有点焦虑`、`你可能焦虑`
   属共情镜像，放行；`你抑郁了`、`你可能抑郁了`、`这属于抑郁症` 属结论，拦截。
2. 检测前做 NFKC 归一化并去掉全部空白（含换行），因此模型输出的
   `你有抑\\n郁症`、`你 患 上 了 抑 郁 症`、`ＳＳＲＩ` 都能识别。

流式场景（`OutputGuard`）的关键约束：违规句可能被拆在多个 chunk 里，
因此**任何已经下发的文本都不能再与后续文本拼成违规句**。做法是只在句末
标点处切分；若模型长时间不给标点，则保留末尾 `_HOLD_BACK` 个字符不发送，
只下发此前部分。`_HOLD_BACK` 大于任一规则的最大匹配跨度，因此跨切点的
违规句必然整体落在保留区，等切分点出现（或 flush）时再整体判定。
"""
from __future__ import annotations

import re
import unicodedata

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
    "惊恐障碍|社交恐惧症|社交焦虑障碍|躯体化障碍|疑病症|失眠症|"
    "抑郁障碍|焦虑障碍"
)
_DISORDER_RE = re.compile(f"({_DISORDERS})", re.IGNORECASE)

# 裸病名：只有出现在判断/推断/归类语境时才构成诊断结论
_BARE_RE = re.compile(r"(抑郁|焦虑)")

# 强判断/确诊动词：直接下结论
_DIAG_VERB_RE = re.compile(
    r"就是|属于|患有|患了|患上了?|得了|确诊(?:为|是)?|诊断(?:为|是)?|符合|典型"
)
# 分度/倾向词（轻中度、疑似…）
_SEVERITY_RE = re.compile(r"轻度|中度|重度|轻中度|疑似|偏重|倾向(?:于)?")
# 推测词
_INFER_RE = re.compile(r"可能|也许|大概|似乎|好像|听起来|看起来|像是|像|疑似")
# 人称代词
_PERSON_RE = re.compile(r"你|您|ta|他|她")
# 无主语的归类句式（这属于 / 这就是）
_CLASSIFY_RE = re.compile(r"(?:这|那|这个|这种情况|这情况|以上)(?:也)?(?:就)?(?:是|属于|算)")
# 共情强度修饰：出现即视为「情绪描述」而非诊断结论
_DEGREE_RE = re.compile(
    r"有点|有些|有点儿|一点|挺|蛮|比较|稍微|特别|非常|那么|这么|很多|太多"
)
# 否定诊断（「你不是抑郁症」「并没有抑郁」）不构成结论
_NEGATED_DIAGNOSIS_RE = re.compile(r"(?:不是|没有|并非|算不上|不属于)$")

_DRUGS = (
    # 通用名
    "舍曲林|氟西汀|帕罗西汀|氟伏沙明|艾司西酞普兰|西酞普兰|文拉法辛|度洛西汀|"
    "米氮平|曲唑酮|丁螺环酮|劳拉西泮|阿普唑仑|氯硝西泮|地西泮|奥氮平|喹硫平|"
    "丙戊酸钠|碳酸锂|唑吡坦|右佐匹克隆|阿米替林|多塞平|氯米帕明|舍曲林片|"
    "氟哌啶醇|坦度螺酮|奥沙西泮|"
    # 常见商品名（患者/模型更常说品牌名）
    "百忧解|左洛复|来士普|赛乐特|怡诺思|欣百达|瑞美隆|思诺思|黛力新|"
    "舒乐安定|佳静安定|安定片|阿普唑仑片|米安色林|曲舍林|"
    # 药品类别（SSRI/SNRI 等缩写模型经常直接说）
    "SSRI|SNRI|安眠药|褪黑素|抗抑郁药|抗焦虑药|镇静剂|抗精神病药"
)
_DRUGS_RE = re.compile(rf"({_DRUGS})", re.IGNORECASE)

# 停药/减药/自行调整剂量：属于「用药指导」，无论是否推荐具体药名都拦截
_STOP_ADVICE_RE = re.compile(
    r"(?:停药|减药|减量|停掉|断药|断了药|不用吃了|可以停|自行停|"
    r"减少剂量|加大剂量|调整剂量|换药|加量)"
)
# 否定/遵医嘱语境：同一分句内出现即视为安全叮嘱，不拦截
_NEGATION_RE = re.compile(r"(?:不要|不能|不可|别|勿|切勿|避免|禁止|不建议|遵医嘱|听医生|按医生)")
_CLAUSE_SPLIT_RE = re.compile(r"[，,；;。！？!?]")

# 疗效承诺：
# 1) 无条件强承诺（根治/包治/一次见效/保证治愈…）直接拦截；
# 2) 「治疗语境 + 结果承诺」拦截（坚持吃药就会好起来）；
# 3) 单纯祝福（你一定会好起来的）放行，中性用药叮嘱（按医嘱服药）放行。
_EFFICACY_STRONG_RE = re.compile(
    r"根治|包治|药到病除|立竿见影|一次见效|治愈率|彻底治愈|永不复发|包好|"
    r"保证(?:能|会|可以)?(?:治好|治愈|康复|痊愈|好起来)|"
    r"(?:一定|肯定|绝对|百分百|100%)(?:能|会)(?:治好|治愈|康复|痊愈)|"
    r"百分百(?:能|会)?(?:治好|治愈|好)"
)
_TREATMENT_CTX_RE = re.compile(r"吃药|服药|用药|药物|这个药|那种药|治疗|疗法|疗程")
_EFFICACY_RESULT_RE = re.compile(
    r"(?:就|一定|肯定|保证|绝对|百分百|包|很快|马上|几天|一周|两周|一个月|坚持)"
    r"(?:能|会|可以|就能|就会|即可)?(?:治好|治愈|康复|痊愈|好起来|见效)"
)

# 分句但保留分隔符，便于按句替换。
# 换行不作为句子边界：模型可能把词写在两行（「你有抑\n郁症」），
# 拆行会让两半都逃过检测；sanitize 会在检测副本上跨行拼接，
# 命中后只替换参与命中的那几行（见 `_split_segments` / `_mark_cross_line_hits`）。
_SENTENCE_RE = re.compile(r"(?<=[。！？!?])")

# 流式切分点：只在句末标点后切（含换行同理）
_TERMINATOR_RE = re.compile(r"[。！？!?]")
# 句末标点集合（判断「上一行是否已经是完整句」，决定能否跨行拼接检测）
_TERMINATORS = "。！？!?"
# 跨行拼接的最大字符数：只用于把被换行拆开的词拼回来，不做长距离上下文串联
_CROSS_LINE_MAX_CHARS = 48
# 无标点时的保留窗口：必须大于任一规则的最大匹配跨度，
# 否则一个违规句可能被切在「已下发」与「保留区」两侧（上一轮 200 字强制切分即此缺陷）。
_HOLD_BACK = 48


def _squash(text: str) -> str:
    """NFKC（全角→半角）+ 去掉所有空白，消除换行/空格/全角造成的断词。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _before(text: str, index: int, size: int = 14) -> str:
    return text[max(0, index - size) : index]


def _diagnosis(text: str) -> bool:
    """判断一句话是否在给用户下诊断结论（而非描述情绪）。"""
    # 1) 明确病名：需要判断/分度/推断/归类语境，单纯科普「抑郁症很常见」放行
    for match in _DISORDER_RE.finditer(text):
        pre = _before(text, match.start())
        if _NEGATED_DIAGNOSIS_RE.search(pre):
            continue
        if _DIAG_VERB_RE.search(pre) or _SEVERITY_RE.search(pre) or _CLASSIFY_RE.search(pre):
            return True
        if _PERSON_RE.search(pre) and (_INFER_RE.search(pre) or re.search(r"[是有]", pre)):
            return True
        if re.search(r"(?:这|那|这个|这种情况|这情况)", pre) and (
            _INFER_RE.search(pre) or re.search(r"[是有]", pre)
        ):
            return True
        if _INFER_RE.search(pre) and re.search(r"像|听起来|看起来|似乎", pre):
            return True

    # 2) 裸病名：必须带结论性语境才算诊断；「有点/有些」等共情修饰放行
    for match in _BARE_RE.finditer(text):
        if text[match.end() : match.end() + 1] == "症":
            continue  # 明确病名，已在上面的分支处理
        pre = _before(text, match.start(), 12)
        post = text[match.end() : match.end() + 3]
        if _NEGATED_DIAGNOSIS_RE.search(pre):
            continue
        if post.startswith(("情绪", "感受", "心情", "状态")):
            continue
        if _DIAG_VERB_RE.search(pre) or _SEVERITY_RE.search(pre) or _CLASSIFY_RE.search(pre):
            return True
        if _DEGREE_RE.search(pre):
            continue
        # 「你可能抑郁了」「你抑郁了」：完成体「了」+ 人称/推测
        if post.startswith("了") and (_PERSON_RE.search(pre) or _INFER_RE.search(pre)):
            return True
        # 「你有焦虑」「你是抑郁」：判断/存在动词紧邻裸病名
        if re.search(r"(?:是|有)[^，。！？]{0,2}$", pre):
            return True
    return False


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


def _efficacy_hit(sentence: str) -> bool:
    if _EFFICACY_STRONG_RE.search(sentence):
        return True
    return bool(_TREATMENT_CTX_RE.search(sentence) and _EFFICACY_RESULT_RE.search(sentence))


def detect(sentence: str) -> str | None:
    """返回该句命中的违规类别（diagnosis/medication/efficacy），未命中返回 None。"""
    text = _squash(sentence)
    if _diagnosis(text):
        return "diagnosis"
    if _drug_or_advice_hit(text):
        return "medication"
    if _efficacy_hit(text):
        return "efficacy"
    return None


def _split_segments(text: str) -> list[dict]:
    """把回复切成「可替换的最小单元」：先按换行，再按句末标点。

    每个 segment 记录 `newline_before`，渲染时据此还原原始换行，
    保证「只替换命中句」不会把整段多行文本压成一段。
    """
    segments: list[dict] = []
    for line_index, line in enumerate(text.split("\n")):
        first_in_line = True
        for piece in _SENTENCE_RE.split(line):
            if not piece:
                continue
            segments.append(
                {"text": piece, "newline_before": line_index > 0 and first_in_line}
            )
            first_in_line = False
        if first_in_line:
            # 空行：保留一个纯换行单元，避免多段之间被压扁
            segments.append(
                {"text": "", "newline_before": line_index > 0, "raw": True}
            )
    return segments


def _joinable(previous: dict) -> bool:
    """上一行没有句末标点时才认为「同一句被换行拆开」，允许跨行拼接检测。

    若上一行已是完整句（以 `。！？!?` 收尾），拼接会把两句话的上下文串起来，
    容易把下一行的科普句误判成对用户的诊断结论，因此不拼接。
    """
    text = previous["text"]
    return bool(text) and text[-1] not in _TERMINATORS


def _mark_cross_line_hits(segments: list[dict]) -> None:
    """跨行断词二次判定：只给参与命中的连续 segment 打标，不做整段替换。

    单行检测已能覆盖「你 患 上 了 抑 郁 症」这类空格断词；这里只处理
    换行造成的断词（「你有抑\\n郁症」「你的情况\\n可能是抑郁症」）。拼接仅在
    `_joinable` 成立（上一行不是完整句）时进行，窗口总长受
    `_CROSS_LINE_MAX_CHARS` 限制，且窗口内每个 segment 单独判定都未命中。
    """
    total = len(segments)
    index = 0
    while index < total:
        if segments[index].get("replace_cat"):
            index += 1
            continue
        # 可拼接的连续片段区间 [index, run_end)
        run_end = index + 1
        size = len(segments[index]["text"])
        while run_end < total and _joinable(segments[run_end - 1]):
            next_size = len(segments[run_end]["text"])
            if size + next_size > _CROSS_LINE_MAX_CHARS:
                break
            size += next_size
            run_end += 1
        if run_end - index < 2:
            index += 1
            continue

        matched: tuple[int, str] | None = None
        for stop in range(index + 2, run_end + 1):
            if any(seg.get("replace_cat") for seg in segments[index:stop]):
                break
            category = detect("".join(seg["text"] for seg in segments[index:stop]))
            if category:
                matched = (stop, category)
                break
        if matched is None:
            index += 1
            continue

        stop, category = matched
        start = index
        # 收缩到「真正命中的最小窗口」：避免把同一句里正常的前半句一起吞掉
        # （「我今天有点累\n你可能是抑郁症」里，命中点从第二行才开始）。
        shrunk = True
        while shrunk:
            shrunk = False
            for candidate in range(start + 1, stop):
                if detect("".join(seg["text"] for seg in segments[candidate:stop])):
                    start = candidate
                    shrunk = True
                    break
        for seg in segments[start:stop]:
            seg["replace_cat"] = category
        index = stop


def sanitize(
    text: str, inserted: set[str] | None = None
) -> tuple[str, list[str]]:
    """按句过滤整段回复：违规句替换为安全话术，返回 (安全文本, 命中类别列表)。

    替换粒度是「句」而不是「段」：多行回复里只有一句违规时，其余句子与
    换行原样保留；跨换行的断词句只替换参与命中的那几行。

    `inserted` 由调用方传入可在多次调用间共享（流式守卫用它避免同类安全话术重复插入）。
    """
    if not text:
        return text, []
    segments = _split_segments(text)
    for seg in segments:
        if not seg.get("raw"):
            seg["replace_cat"] = detect(seg["text"])
    _mark_cross_line_hits(segments)

    hits: list[str] = []
    seen = inserted if inserted is not None else set()
    out: list[str] = []
    prev_replaced = False
    for seg in segments:
        separator = "\n" if seg["newline_before"] else ""
        category = seg.get("replace_cat")
        if category is None:
            out.append(separator + seg["text"])
            prev_replaced = False
            continue
        if category not in hits:
            hits.append(category)
        # 与上一个被替换句相邻时丢弃换行，避免安全话术之间出现空行
        if not prev_replaced and separator and out:
            out.append(separator)
        # 同类违规话术在同一条回复内只插入一次，避免安全提示刷屏
        if category not in seen:
            seen.add(category)
            out.append(SAFE_TEXT[category])
        prev_replaced = True
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
