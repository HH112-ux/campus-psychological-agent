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

# ---------- 归一化 vs 原文（红线约定，勿破） ----------
# 模式匹配可以跑 `_squash`（NFKC + 繁简归并 + 去空白）；但「前后文邻接 / 豁免 /
# 边界判定」必须使用**保留标点**的文本：
# - `_squash` 只去空白，**保留标点**，因此 `_diagnosis` 里的 `pre` / `post` 切片是安全的；
# - 换行是硬边界：只能由 `_split_segments` 切开、再由 `_cross_line_join_allowed`
#   显式判定「能否拼接」，任何函数都不得先抹掉 `\n` 再做邻接判断；
# - 禁止用 `app.core.text.normalize`（它会删标点）做任何边界判断——危机侧
#   「想死你」吞句、寒暄前缀剥离、碰撞豁免三次同形漏报都源于在去标点文本上判邻接。

# 违规句替换话术（短句，避免进一步给出任何建议性结论）
SAFE_TEXT: dict[str, str] = {
    "diagnosis": "我不能给出诊断，具体需要专业医生评估。",
    "medication": "用药请一定听专业医生的，不要自行加量或停药。",
    "efficacy": "我没法保证效果，具体进展需要专业评估。",
}

# 精神科常见诊断名（明确病名）
_DISORDERS = (
    "抑郁症|忧郁症|焦虑症|双相情感障碍|双相障碍|躁郁症|强迫症|精神分裂症|精神分裂|"
    "创伤后应激障碍|PTSD|进食障碍|人格障碍|多动症|ADHD|自闭症|"
    "惊恐障碍|社交恐惧症|社交焦虑障碍|躯体化障碍|疑病症|失眠症|"
    "抑郁障碍|焦虑障碍"
)
_DISORDER_RE = re.compile(f"({_DISORDERS})", re.IGNORECASE)

# 裸病名：只有出现在判断/推断/归类语境时才构成诊断结论
_BARE_RE = re.compile(r"(抑郁|忧郁|焦虑)")

# 强判断/确诊动词：直接下结论（「患(?!者)」排除「抑郁症患者」这类科普主语）
_DIAG_VERB_RE = re.compile(
    r"就是|属于|患有|患了|患上了?|患(?!者)|得了|确诊(?:为|是)?|诊断(?:为|是)?|"
    r"符合|满足|达到|典型"
)
# 分度/倾向词（轻中度、疑似…）
_SEVERITY_RE = re.compile(r"轻度|中度|重度|轻中度|疑似|偏重|倾向(?:于)?")
# 病程/时长：裸病名后接时长，等同于「你已经病了多久」的结论式判断。
# 按「修饰词 + 数量词 + 时间单位」的语义结构匹配，而不是切片固定字符窗口：
# 「很长时间」「很多年」「很久」「好几年」「大半年」「几个月」「半个月」
# 都能命中，也不会因为「很长时间」比「很久」多两个字就漏。
_TIME_UNIT = r"(?:时间|年|个月|月|周|星期|天)"
_DURATION_RE = re.compile(
    r"(?:已经|也|都|有)?"
    r"(?:"
    r"(?:很|好|太|这么|那么|挺|相当)?(?:久|长|多年|好几年|几年|大半年|小半年|半年|一阵)"
    r"|(?:很|好|太|这么|那么|挺|相当)(?:多|长)?(?:一段)?" + _TIME_UNIT +
    r"|(?:多|长)(?:一段)?" + _TIME_UNIT +
    r"|一段" + _TIME_UNIT +
    r"|(?:好)?(?:几|几十|十几|半|两|\d+|[一二三四五六七八九十]+)(?:个)?" + _TIME_UNIT +
    r")"
)
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
    "丙戊酸钠|碳酸锂|唑吡坦|右佐匹克隆|佐匹克隆|阿米替林|多塞平|氯米帕明|舍曲林片|"
    "氟哌啶醇|坦度螺酮|奥沙西泮|艾司唑仑|氯氮平|安非他酮|阿立哌唑|鲁拉西酮|"
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


# 繁体/异体字 → 简体：NFKC 只做兼容分解，不处理繁简，模型输出繁体时病名/药名会漏。
# 覆盖范围 = 规则词表（_DISORDERS / _DRUGS / 判断词 / 疗效词）里每个字的繁体写法，
# 不引入完整繁简转换依赖（离线部署）。
# 维护约束：新增病名/药名时，必须同步补齐该词的繁体字形；tests 里的
# `TRAD_DIAGNOSIS_FORMS` / `TRAD_MEDICATION_FORMS` 逐词生成繁体写法并断言可识别，
# 词表新增而映射缺字会让该测试直接失败。
_T2S = str.maketrans(
    {
        "點": "点", "鬱": "郁", "慮": "虑", "靜": "静", "藥": "药", "醫": "医",
        "療": "疗", "癒": "愈", "復": "复", "剋": "克", "侖": "仑", "錠": "锭",
        "劑": "剂", "礙": "碍", "強": "强", "雙": "双", "衝": "冲", "顯": "显",
        "邊": "边", "開": "开", "體": "体", "聯": "联", "們": "们", "這": "这",
        "說": "说", "會": "会", "與": "与", "為": "为", "麼": "么", "個": "个",
        "還": "还", "樣": "样", "後": "后", "裡": "里", "覺": "觉",
        "斷": "断", "減": "减", "種": "种", "當": "当", "發": "发",
        # —— 病名 ——
        "憂": "忧", "創": "创", "傷": "伤", "應": "应", "進": "进",
        "動": "动", "閉": "闭", "驚": "惊", "懼": "惧", "軀": "躯",
        # —— 药名（通用名 + 商品名 + 类别）——
        "蘭": "兰", "羅": "罗", "環": "环", "勞": "劳", "奧": "奥", "鈉": "钠",
        "鋰": "锂", "魯": "鲁", "來": "来", "賽": "赛", "樂": "乐",
        "諾": "诺", "達": "达", "鎮": "镇",
        # —— 判断/疗效/用药词（保证「確診」「換藥」「見效」等语境同样可识别）——
        "診": "诊", "確": "确", "屬": "属", "於": "于", "許": "许", "聽": "听",
        "傾": "倾", "較": "较", "蠻": "蛮", "兒": "儿", "見": "见", "證": "证",
        "徹": "彻", "換": "换", "調": "调",
    }
)


def _squash(text: str) -> str:
    """NFKC（全角→半角）+ 繁简归并 + 去掉所有空白，消除换行/空格/全角/繁体断词。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).translate(_T2S))


def _before(text: str, index: int, size: int = 14) -> str:
    return text[max(0, index - size) : index]


# 直接指向用户的人称：与第三方主语同时出现时，仍按「对用户下结论」处理
_USER_RE = re.compile(r"你|您")
# 第三方/转述主语：「我有个朋友得了抑郁症」「医生说他有抑郁症」不是对用户的诊断
_THIRD_PARTY_RE = re.compile(
    r"我(?:有个|有一个|的一个|的)?(?:朋友|同学|室友|闺蜜|同事|表姐|表哥|表妹|表弟|"
    r"弟弟|妹妹|哥哥|姐姐|家人|亲戚)"
    r"|朋友|同学|室友|闺蜜|同事|表姐|表哥|表妹|表弟|家人|亲戚"
    r"|医生说|咨询师说|老师说|老师提到|他|她"
)
# 科普主语：「抑郁症患者常有这种表现」是在讲群体，不是在给用户下结论。
# 注意：这里只是「候选」——必须先确认主语不指向用户才能豁免，
# 否则「你是抑郁症患者」「你可能是一名抑郁症患者」会被一起放行。
_GENERIC_SUBJECT_RE = re.compile(r"患者|病人|的人|人群|病友|群体")
# 用户本人充当「患者」的句式：「你作为抑郁症患者」「身为抑郁症患者的你」
_USER_ROLE_PRE_RE = re.compile(r"(?:你|您)(?:也)?(?:作为|身为|是|就?是|属于)")
_USER_ROLE_POST_RE = re.compile(r"(?:患者|病人)(?:之一)?(?:的)?(?:你|您)")
# 科普/泛指语境（「有些人可能会得抑郁症」），用于豁免「推测词 + 明确病名」判定
_GENERIC_PRE_RE = re.compile(r"有些人|有人|有的人|很多人|人们|大家")


def _third_party(pre: str) -> bool:
    """第三方/转述语境：有第三方主语且没有直接指向用户（你/您）。"""
    return bool(_THIRD_PARTY_RE.search(pre)) and not _USER_RE.search(pre)


def _user_subject(pre: str, post: str) -> bool:
    """这一处病名的中心语/主语是否指向用户本人。

    - 「身为抑郁症患者的你」「…患者之一」：中心语就是「你」，指向用户；
    - 第三方/转述主语且整句没有「你/您」：不指向用户；
    - 病名前出现「你/您」（你是… / 你作为… / 你可能是一名…）：指向用户。
    """
    if _USER_ROLE_POST_RE.match(post):
        return True
    if _third_party(pre):
        return False
    return bool(_USER_RE.search(pre))


def _diagnosis(text: str) -> bool:
    """判断一句话是否在给用户下诊断结论（而非描述情绪）。"""
    # 1) 明确病名：需要判断/分度/推断/归类语境，单纯科普「抑郁症很常见」放行
    for match in _DISORDER_RE.finditer(text):
        pre = _before(text, match.start())
        post = text[match.end() : match.end() + 10]
        # 「患者/病人」只在主语明确是第三方或泛称时豁免；指向用户时不豁免
        if _GENERIC_SUBJECT_RE.match(post) and not _user_subject(pre, post):
            continue
        if _third_party(pre):
            continue
        if _NEGATED_DIAGNOSIS_RE.search(pre):
            continue
        # 「你作为抑郁症患者」「身为抑郁症患者的你」：用户本人即患者
        if _USER_ROLE_PRE_RE.search(pre) or _USER_ROLE_POST_RE.match(post):
            return True
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
        # 推测词 + 明确病名（无第三方/泛指主语）：「可能是抑郁症」只有在换行把
        # 主语隔开时才没有「你」，但仍是推测式诊断，必须拦。
        if _INFER_RE.search(pre) and not _GENERIC_PRE_RE.search(pre):
            return True
        # 「你抑郁症很长时间了」：明确病名 + 时长，同样是病程结论
        if (_PERSON_RE.search(pre) or _INFER_RE.search(pre)) and _DURATION_RE.match(post):
            return True

    # 2) 裸病名：必须带结论性语境才算诊断；「有点/有些」等共情修饰放行
    for match in _BARE_RE.finditer(text):
        if text[match.end() : match.end() + 1] == "症":
            continue  # 明确病名，已在上面的分支处理
        pre = _before(text, match.start(), 12)
        post = text[match.end() : match.end() + 10]
        if _third_party(pre):
            continue
        if _GENERIC_SUBJECT_RE.match(post) and not _user_subject(pre, post):
            continue
        if _NEGATED_DIAGNOSIS_RE.search(pre):
            continue
        if post.startswith(
            (
                "情绪", "感受", "心情", "状态",
                "的情绪", "的感受", "的心情", "的状态", "的感觉",
            )
        ):
            continue
        # 「我研究的是焦虑的成因」「这是一本关于抑郁的书」：裸病名作定语，
        # 讨论的是课题/成因/文献，不是给用户下结论（第五轮 H-2）。
        if re.match(r"的(?:成因|机制|研究|课题|定义|概念|书|文章|文献|报道|科普)", post):
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
        # 「你抑郁很久了吧」「听起来你已经抑郁很久了」：时长即病程结论
        if _DURATION_RE.match(post):
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
    """返回该句命中的违规类别（diagnosis/medication/efficacy），未命中返回 None。

    多行输入按与 `sanitize` 完全相同的跨行规则判定，保证「检测」与「替换」口径一致，
    不会把两行独立句子压成一句假诊断。
    """
    if "\n" in sentence:
        _, hits = sanitize(sentence)
        return hits[0] if hits else None
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


# 语气/完成体助词：换行正好落在术语末尾时，下一行只有以这些字开头才算「词被拆开」
_PARTICLES = "了吧吗呢啊呀哦哈"

# 跨行拼接只认「词表术语被换行切断」：把相邻两行拼起来时，只有拼接处确实落在
# 某个已知术语（病名/药名/用药与疗效词）内部，才允许做跨行判定。这样「你有抑
# \n郁症」仍会被拦，而「你最近是不是睡不好\n抑郁症患者常有这种表现」不会把上一
# 行的人称/判断词借给下一行的独立句子（第三轮复审 H-1 的误拦根因）。
_TERM_TOKENS: tuple[str, ...] = tuple(
    sorted(
        {
            *(term for term in _DISORDERS.split("|") if term),
            *(term for term in _DRUGS.split("|") if term),
            "抑郁", "焦虑",
            "停药", "减药", "减量", "加量", "换药", "断药", "治疗", "服药",
            "吃药", "用药", "根治", "治愈", "痊愈", "康复", "复发", "见效",
            "好起来", "药到病除", "立竿见影", "一次见效",
        },
        key=len,
        reverse=True,
    )
)


# 判断/推测线索词：换行可能正好落在「线索词 | 病名」之间（「你得了\n抑郁症」
# 「你可能\n是抑郁症」）。只有上一段**以线索词收尾**时才允许继续往下一行拼，
# 因此「你最近是不是睡不好\n抑郁症患者常有这种表现」这类普通叙述不会被拼接。
# 线索词允许后面紧跟完成体/语气词、宾语人称与量词定语（见 `_CUE_TAIL_CHARS`）：
# 「你已经确诊了」「你被确诊了」「医生已经诊断你为」「你是一名」「你可能是一位」
# 都应按「线索词收尾」处理，而不是要求上一个字符恰好是线索词最后一个字。
_CUE_TOKENS: tuple[str, ...] = (
    "患上了", "患有", "患了", "患上", "得了",
    "确诊为", "确诊是", "诊断为", "诊断是", "确诊", "诊断",
    "符合", "满足", "达到", "属于", "作为", "就是", "可能是",
    "好像", "可能", "也许", "大概", "疑似", "是",
)
# 线索词之后允许的尾缀字符：完成体/语气词（了/啦/的/过）、指向用户的人称（你/您）、
# 介词（为）、量词定语（一/位/个/名）。判定方式是从段尾剥离这些字符再比对线索词，
# 而不是用「固定字偏移阈值」把「一名」「作为」这类两三字的引导卡掉。
# 不收「我/他/她」：那会把「你是我的 | 抑郁症朋友」这类叙述也借到下一行。
_CUE_TAIL_CHARS = "了啦的过你您一位个名为"
# 换行后到术语之间允许出现的引导串（「可能\n是抑郁症」的「是」、
# 「你是一名\n一个抑郁症患者」的「一个」）。只认白名单组合，长度不限但成分受限，
# 因此不需要再设 `offset > 2` 之类的硬阈值。
_LEAD_CUE_RE = re.compile(
    r"^(?:(?:是|为|属于|就是|得了|患了|患上|患有|有|一名|一位|一个|个|名))*$"
)


def _ends_with_cue(previous: str) -> bool:
    """上一段是否以「线索词 + 可选尾缀」收尾（只认 `_CUE_TOKENS` 白名单）。

    - 「你得了」→ 直接命中线索词「得了」；
    - 「你已经确诊了」→ 先剥尾缀「了」，剩下「你已经确诊」以「确诊」收尾；
    - 「医生已经诊断你为」→ 剥尾缀「为你」，剩下「医生已经诊断」以「诊断」收尾；
    - 「你可能是一名」→ 剥尾缀「一名」，剩下「你可能是」以「是」收尾。
    剥不干净（尾缀里混入实词）就不算线索词收尾，避免把普通叙述借给下一行。
    """
    if any(previous.endswith(cue) for cue in _CUE_TOKENS):
        return True
    end = len(previous)
    while end > 0 and previous[end - 1] in _CUE_TAIL_CHARS:
        end -= 1
    if end == len(previous):
        return False
    return any(previous[:end].endswith(cue) for cue in _CUE_TOKENS)


def _cross_line_join_allowed(segments: list[dict], start: int, stop: int) -> bool:
    """窗口内的换行是否属于「把一句话切断」，从而允许跨行判定。

    只认三类换行，其余一律视为独立句子、不拼接：
    1. 换行落在词表术语内部（`你有抑` / `郁症`）；或正好在术语末尾且下一行以
       语气词开头（`你 抑郁` / `了`）——断的是「词 + 语气」；
    2. 换行落在「判断线索词 | 病名」之间：上一段以 `_CUE_TOKENS` 收尾（允许夹
       完成体/语气词/宾语人称/量词尾缀，见 `_ends_with_cue`），且下一段在换行处
       到术语之间只有白名单引导串（`_LEAD_CUE_RE`）；
    3. 换行落在病名后的定语「的」之后（`你满足抑郁症的` / `诊断标准`），且病名
       之前确实有线索词。
    第 2/3 类都要求「上一段确实带线索词」，而不是任意结尾，避免把人称/上下文
    借给下一行的独立句子（第三轮 H-1 的误拦根因）。
    """
    text = ""
    boundaries: list[int] = []
    for seg in segments[start:stop]:
        part = _squash(seg["text"])
        if text:
            boundaries.append(len(text))
        text += part
    if not text or not boundaries:
        return False
    lowered = text.lower()

    for term in _TERM_TOKENS:
        needle = term.lower()
        index = lowered.find(needle)
        while index != -1:
            end = index + len(needle)
            for boundary in boundaries:
                if index < boundary < end:
                    return True
                if boundary == end and boundary < len(text) and text[boundary] in _PARTICLES:
                    return True
            index = lowered.find(needle, index + 1)

    for boundary in boundaries:
        previous = text[:boundary]
        if _ends_with_cue(previous):
            following = text[boundary:]
            for term in _TERM_TOKENS:
                offset = following.lower().find(term.lower())
                if offset == -1:
                    continue
                if _LEAD_CUE_RE.match(following[:offset]):
                    return True

        # 3. 病名在上一段末尾、换行落在定语「的」之后（「你满足抑郁症的 | 诊断标准」）：
        #    只有病名之前确实出现线索词时才拼接，避免把「我研究抑郁症的 | 成因」
        #    这类定语结构拼成诊断结论。
        for term in _TERM_TOKENS:
            if not previous.endswith(term + "的"):
                continue
            head = previous[: -len(term) - 1]
            if any(cue in head[-8:] for cue in _CUE_TOKENS):
                return True
    return False


def _is_single_char_fragment(seg: dict) -> bool:
    """单字行（模型按字换行的残片）：不是整句，也没有句末标点。"""
    text = seg["text"].strip()
    return len(text) == 1 and text not in _TERMINATORS


def _mark_cross_line_hits(segments: list[dict]) -> None:
    """跨行断词二次判定：只给参与命中的连续 segment 打标，不做整段替换。

    单行检测已能覆盖「你 患 上 了 抑 郁 症」这类空格断词；这里只处理
    换行造成的断词（「你有抑\\n郁症」）。拼接需要同时满足：
    1. `_joinable`：上一行不是完整句（避免跨句借上下文）；
    2. `_cross_line_join_allowed`：换行处确实切断了词表术语，或正好切在
       「判断线索词 | 病名」之间（避免把人称/上下文借给下一行的独立句子）；
    3. 窗口总长受 `_CROSS_LINE_MAX_CHARS` 限制；窗口内的后续行若已单独命中则不再
       跨越（起点行例外，用于把「病名 + 的」后面的定语一并替换掉）。
    """
    total = len(segments)
    index = 0
    while index < total:
        # 已命中的行也可以是拼接窗口的起点：像「你满足抑郁症的 | 诊断标准」这种
        # 结构，首行单行判定即命中，后续行只是被判定的定语，需要一起替换，
        # 否则会留下「[安全话术]\n诊断标准」这种残句。
        if segments[index].get("replace_cat") and not _joinable(segments[index]):
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
            # 不跨越「已经替换过的后续行」；起点行允许已命中（见上面的说明）。
            if any(seg.get("replace_cat") for seg in segments[index + 1 : stop]):
                break
            if not _cross_line_join_allowed(segments, index, stop):
                continue
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
        # 残字收敛：命中片段被单字行包围时（模型按字换行），把相邻单字行一并纳入，
        # 避免输出里留下「你\n[安全话术]\n症」这种孤立残字。
        while start > 0 and _is_single_char_fragment(segments[start - 1]):
            start -= 1
        while stop < total and _is_single_char_fragment(segments[stop]):
            stop += 1
        for seg in segments[start:stop]:
            # 已有的类别不覆盖：已命中的行按原类别替换，新增行沿用本次类别
            if not seg.get("replace_cat"):
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
    prev_cat: str | None = None
    for seg in segments:
        separator = "\n" if seg["newline_before"] else ""
        category = seg.get("replace_cat")
        if category is None:
            out.append(separator + seg["text"])
            prev_cat = None
            continue
        if category not in hits:
            hits.append(category)
        # 与上一个被替换句「同类」时既不重复插入话术，也不补换行；
        # 不同类时保留换行，避免「诊断话术」「用药话术」被压成一行。
        if separator and out and prev_cat != category:
            out.append(separator)
        # 同类违规话术在同一条回复内只插入一次，避免安全提示刷屏
        if category not in seen:
            seen.add(category)
            out.append(SAFE_TEXT[category])
        prev_cat = category
    return "".join(out), hits


def _hold_back_cut(buf: str) -> int:
    """按 `_HOLD_BACK` 个「归一化后字符」计算保留窗起点（返回可下发的切点）。

    保留窗必须覆盖规则的最大匹配跨度，而规则跑在 `_squash` 后的文本上：
    逐字换行、成片空格会让同一个违规句的原始长度远大于归一化长度
    （「疑 似 患 有 …」原始 70 字，归一化仅 12 字）。按原始字符切会把
    违规句拆到「已下发 / 保留区」两侧，因此这里逐字符累加 `_squash` 长度。
    """
    kept = 0
    index = len(buf)
    while index > 0:
        index -= 1
        kept += len(_squash(buf[index]))
        if kept >= _HOLD_BACK:
            return index
    return 0


class OutputGuard:
    """流式输出的合规守卫：按句缓冲，feed/flush 返回已可安全下发的内容。

    切分规则：
    1. 有句末标点：切到最后一个句末标点，整句判定后下发；
    2. 无句末标点：仅当缓冲的「归一化后长度」超过 `_HOLD_BACK` 时，下发此前缀，
       末 `_HOLD_BACK` 个归一化字符保留到下一轮。保留窗大于规则最大匹配跨度，
       跨窗违规句因此仍会被整体判定。
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
        if not cut:
            cut = _hold_back_cut(self._buf)
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
