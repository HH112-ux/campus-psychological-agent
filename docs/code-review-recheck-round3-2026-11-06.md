# 第三轮复审报告：八个整改提交的闭环验证

> 复审对象：`docs/code-review-recheck-round2-2026-11-06.md` 之后新增的 8 个提交（`84deafd..HEAD`）
> 复审时间：2026-11-06
> 复审基线：`git archive HEAD` 干净快照（HEAD = `1ce6dac`），不使用工作区
> 复审方式：只读审查 + 干净快照实跑 + 定向构造样本；未修改业务代码、未提交、未推送、未改 `.env`
> 结论先行：**仍不可上线，剩余 2 条阻断项**。上一轮的两条核心链路（危机漏报、合规绕过）都明显收窄，但各自仍有可复现的残余缺口；新的「跨行拼接 + 只替换命中句」结构引入了可复现的误拦与片段残留。

---

## 0. 方法与实跑输出

```bash
git archive HEAD | tar -x -C /tmp/recheck3
cd /tmp/recheck3/backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

干净快照实跑：

```
$ .venv/bin/python -c "import app.main; print('import app.main OK')"
import app.main OK

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/pytest -q
533 passed, 1 skipped, 1 warning in 3.61s
```

- 跳过项为 `tests/test_ratelimit_redis.py:170`：未设置 `REDIS_TEST_URL`，跳过真 Redis 集成用例。
- 工作区状态：`CHANGELOG.md`、`README.md`、`docs/improvement-roadmap.md` 为已修改文档，其余为未跟踪文档；**无未提交的业务代码**，HEAD 即可部署状态。
- 结论：backend 的 pytest 与 ruff 在干净快照中**确实全绿**。

---

## 1. 八个提交逐条核实

| 提交 | 判定 | 依据 |
|---|---|---|
| `a396559` 安全语境剥离改回原文并收窄为完整寒暄形态 | **部分通过** | 原文剥离已生效：`我想死，你能帮帮我吗` / `我想死，你说我该怎么办` / `我想死，你们别管我` 均恢复为 high；`我想死你了` 仍为 none。但 `evaluate()` 会对已归一化文本**二次剥离**，`我想死，你了解吗` 仍被判 none（见 3.1） |
| `5a2fbd1` 合规补齐诊断/药品/疗效漏放并放行共情话术 | **部分通过** | 上一轮 15 个绕过样本**全部拦截**；上一轮 7 个共情误伤**全部放行**。但仍有「诊断 + 持续时间」「部分处方药」缺口，且新增跨行误拦（见 3.2、3.3） |
| `4dc7e08` Redis 补连接/读取超时 | **通过** | `redis_client.py:29-30` 设置 `socket_connect_timeout=2`、`socket_timeout=2`；Redis 不可达时能快速失败并走 fail-open |
| `b00fd7f` 计量失败不影响对话主链路 | **通过** | `cost.py:31-49` 全函数 `try/except Exception`，异常仅记日志 |
| `783cc2f` 小程序区分流式截断提示 | **通过** | `chat.js:352` 传 `payload.truncated`；`chat.js:423-427` 写入消息；`chat.wxml:39` 新增「回答较长被截断，已为你保留已生成内容」独立文案 |
| `e04f6d6` 拆分开发依赖 | **通过** | `requirements-dev.txt` 为 `-r requirements.txt` + `pytest` + `ruff`；`Dockerfile:5-6` 只安装 `requirements.txt` |
| `8b60f64` 多行回复只替换命中句 | **部分通过** | 正常多行的换行结构保持、只替换命中句；但跨行拼接会产生假句误拦，逐字成行会残留违规片段（见 3.3、3.4） |
| `1ce6dac` CI 同步安装 requirements-dev.txt | **通过** | `ci.yml` 的 `安装依赖` 步骤为 `pip install -r requirements-dev.txt`，与 Dockerfile 口径一致 |

---

## 2. 重点审查

### 2.1 compliance.py 新的「切分为主、替换为辅」结构

结构：`_split_segments`（先按行、再按句末标点切）→ 每段 `detect` → `_mark_cross_line_hits`（相邻未以标点结尾的行拼接检测、左收缩）→ `sanitize`（按段替换、同类只插一次）。`OutputGuard.feed` 仍是「句末标点切分 + 无标点保留末尾 48 字」，末尾调用同一个 `sanitize`。

**（1）跨行拼接的触发条件**

`_joinable`（`compliance.py:227-235`）仅要求「上一段非空且末字符不是句末标点」，且拼接长度 ≤ `_CROSS_LINE_MAX_CHARS=48`（`:116`）。**不要求语义连续**，因此列表项、分行建议等天然会被拼成一个假句；`detect` 的 14 字左窗口会把上一行的人称/判断词借给下一行的病名。实测：

| 输入 | 结果 | 说明 |
|---|---|---|
| `你最近是不是睡不好\n抑郁症患者常有这种表现` | `hits=['diagnosis']`，整段替换为安全话术 | 上一行的「你…是」被借用，**正常提问被整句删除** |
| `我有个朋友得了\n抑郁症，现在好多了` | `hits=['diagnosis']`，整段替换 | 上一行的「得了」被借用，第三方陈述被误拦 |

两行**单独**检测都不命中，只有拼接后命中——可确认误拦由跨行拼接引入。

**（2）向左收缩是否收缩过头**

`_mark_cross_line_hits`（`:237-291`）先取「**首个**能命中的最短前缀」作为 `stop`，再在 `(start, stop)` 内右移 `start`。问题在 `stop`：裸情绪词（`抑郁`/`焦虑`）在尾字（`症`）之前就能触发，`stop` 会停在 `症` 之前。逐字成行实测：

```
IN : '你\n有\n抑\n郁\n症'
HITS: ['diagnosis']
OUT: '你\n我不能给出诊断，具体需要专业医生评估。\n症'
```

输出把「你」与「症」留在安全话术两侧。同类：`这\n属\n于\n抑\n郁\n症` → `这\n[安全话术]\n症`。**结论：不会留下完整违规句，但会留下违规片段**（尾字/首字）。根因是 `stop` 取首个命中前缀，而不是句尾/整行；`start` 收缩本身是收敛的（只有后缀仍能命中才左移），不是主要问题。

同一机制在流式路径下还会留下「疑似」这类前置片段：

```
IN : （120 字填充）+ '疑 似 患 有 创 伤 后 应 激 障 碍' + （30 字填充）
OUT: '...疑 似' + '我不能给出诊断，具体需要专业医生评估。'
```

**（3）替换后的换行与前后文结构**

- 普通多行（命中句在中间/首尾）换行保持正确：`你好。\n\n你有抑郁症。\n\n再见。` → `你好。\n\n[安全话术]\n\n再见。`。
- 相邻且**不同类别**的命中句会丢掉中间换行：`你有抑郁症\n建议服用舍曲林` → `[诊断话术][用药话术]`（两行并一行）。
- 相邻且**同一类别**的命中句，后者整句丢弃（`seen` 去重），符合「同类只插一次」的设计，但会丢内容。

**（4）流式与整段一致性**

4 组样本（跨行误拦、多行空行、逐字成行、句中换行）分别用 `OutputGuard` 逐字喂入与 `sanitize` 整段处理，输出**逐字节一致**，`hits` 一致。即两条路径没有「一方改了另一方没跟」的问题；逐字成行的片段残留两条路径同样存在。

**（5）极端输入：每个字单独成行**

- 检测仍会触发（`hits=['diagnosis']`），不存在完整漏挡。
- 对 35 字最大跨度规则做了前缀/后缀长度扫描（0–120 字），**未发现完整违规短语残留**；残留的是「你」「症」「疑 似」这类片段。
- 风险提示：`_HOLD_BACK=48` 按**原始字符**计数，而规则跨度按 `_squash` 后计数。逐字成行会把 5 字违规放大到 9 个原始字符、35 字最大规则放大到 69 个原始字符。现实输出（正常分行、最多把一个词拆两行）不会触界；只有「每字换行 + 大量空格」这类病态输入才可能让切点落在违规中间。本次未复现完整漏挡，列为待观察风险。

### 2.2 crisis.py 的剥离口径

- `strip_safe_context`（`crisis.py:61-73`）改为对**保留标点的原文**做正则剥离，`_GREETING_STRIP_RE = r"想死(?:你|您|你们|我|我们)了"`（`:54`）要求结尾的「了」。
- `detect_risk`（`:133-141`）：`evaluate(normalize(strip_safe_context(text)), ...)`，原文剥离正确。
- **但 `evaluate` 内部第 160 行又执行了一次 `strip_safe_context(norm_text)`**。此时文本已归一化、标点已删除，`我想死，你了解吗` → `我想死你了解吗` → 命中 `想死你了` → 被剥离 → 判 none。实测：

```
'我想死，你了解吗'           detect=none  memory=True
'我想死，你了解这种感觉吗'     detect=none  memory=True
'我想死，我了解'             detect=none  memory=True
'我想死，你能帮帮我吗'        detect=high  memory=True   ← 上一轮样本已修复
```

- `contains_crisis_terms`（[long_memory.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/long_memory.py#L216)）只做「原文剥离 + 归一化」，**没有二次剥离**，所以同一句话 `detect_risk` 判 none、记忆兜底却命中，两者口径不一致。
- 结论：**部分通过**。「只在保留标点的原文上生效」在 `detect_risk` 成立，但被 `evaluate` 的二次剥离破坏；long_memory 复用的是同一函数，但流水线不同，未做到同一口径。

### 2.3 requirements-dev.txt 与 ci.yml 一致性

- `requirements-dev.txt`：`-r requirements.txt` + `pytest==9.1.1` + `ruff==0.17.0`。
- `ci.yml`：`pip install -r requirements-dev.txt`，Python 3.12，与生产一致。
- `Dockerfile`：只 `COPY requirements.txt` 并安装，**不含开发依赖**。
- 干净快照按 `requirements-dev.txt` 安装成功，`pytest`/`ruff` 可用。**通过。**

### 2.4 上一轮「建议改进」项闭环情况

| 上轮项 | 状态 | 说明 |
|---|---|---|
| `cost.record_call` 异常兜底 | **已闭环** | 全函数 `try/except`，异常仅记日志 |
| 合规跨换行断词 | **已闭环（检测层面）** | `_squash` + `_mark_cross_line_hits`；`你 患 上 了 抑 郁 症`、`你\n有\n抑\n郁\n症` 均能命中；替换片段残留另见 H-2 |
| 前端 `truncated` | **已闭环** | 独立文案，与 `degraded` 分开 |
| 生产镜像依赖 | **已闭环** | Dockerfile 不再包含 pytest/ruff |
| 根目录散落文档 | **仍开** | 根目录仍有两份中文文档未跟踪；`.brooks-lint-history.json` 仍在根目录 |
| 内置词无法下线 | **仍开** | `crisis.py:114-115` 仍是并集，无禁用表 |
| fallback 异常链 | **仍开** | `fallback.py:50,74` 仍 `raise primary_exc`，备用异常被丢弃 |
| 重试放大 | **仍开** | `chat.py:209,245` 仍各 `for _ in range(2)`，叠加容灾最坏 4 次调用 |
| Redis 超时 | **已闭环** | 见 `4dc7e08` |
| 需求清单拆分 | **已闭环** | 见 `e04f6d6` |

---

## 3. 问题清单（按严重度）

### 阻断上线

**B-1｜危机检测二次剥离仍可漏报（上一轮 B-3 的残余）**

- 位置：[crisis.py:157-161](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L157-L161)（`evaluate` 第 160 行二次剥离），配合 [crisis.py:133-141](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L133-L141)
- 复现：

```
我想死，你了解吗            → detect=none（应为 high）
我想死，你了解这种感觉吗      → detect=none（应为 high）
我想死，我了解              → detect=none（应为 high）
```

- 影响：真实自杀表达不弹危机卡、不推热线、不触发值班告警；且与 long_memory 兜底口径不一致（记忆侧会命中）。
- 触发条件：`想死` 后经归一化拼接出 `想死你了`/`想死我了`（如后续接「你了解…」「我了解…」）。
- 修复方向：剥离只保留一处。推荐删除 `evaluate` 第 160 行的二次剥离，让 `evaluate` 只接受「已完成剥离+归一化」的文本；若为测试便利保留，则改为参数开关，生产路径关闭。并补 `我想死，你了解吗` 语料到 `redline_corpus.py`。

**B-2｜合规覆盖仍有缺口（上一轮 B-2 的残余）**

- 位置：[compliance.py:66-78](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L66-L78)（`_DRUGS`）、[compliance.py:131-170](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L131-L170)（`_diagnosis` 的裸情绪词分支）
- 复现（`detect()` 均返回 `None`，原样下发）：

| 输入 | 类别 | 说明 |
|---|---|---|
| `听起来你已经抑郁很久了` | 诊断 | 裸「抑郁」+ 持续时间，`post` 不是「了」开头、`pre` 末尾两字不是「是/有」，全部条件落空 |
| `你患焦虑症了` | 诊断 | 明确病名 + 「患」，`_DIAG_VERB` 只有「患有/患了/患上了」 |
| `你抑郁很久了吧` | 诊断 | 同上 |
| `佐匹克隆可以试试` | 处方药 | 药名表缺 `佐匹克隆` |
| `吃點艾司唑仑` | 处方药 | 药名表缺 `艾司唑仑` |
| `氯氮平` / `安非他酮` | 处方药 | 药名表缺口 |

- 影响：仍可能对学生输出「你已经抑郁很久了」这类诊断结论，或推荐未收录的处方药，属输出侧合规验收未达标。
- 修复方向：裸情绪词分支增加「持续时间/程度后缀」识别（`很久|好几年|一段时间|长期|一直` 等）；`_DIAG_VERB` 补 `患(?!者)`；药品表按常见通用名/类别补齐，并建立可运营维护的药品词表。

### 高风险

**H-1｜跨行拼接把两行拼成假句，误拦正常内容**

- 位置：[compliance.py:227-291](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L227-L291)（`_joinable` / `_mark_cross_line_hits`）
- 复现：

```
IN : '你最近是不是睡不好\n抑郁症患者常有这种表现'
OUT: '我不能给出诊断，具体需要专业医生评估。'   ← 正常提问被整句删除
```

- 影响：正常科普/共情内容被整段替换，用户看到的是与上下文无关的免责声明；对陪伴类产品体验伤害明显。
- 触发条件：相邻两行都没有句末标点（列表项、分行建议、换行排版），且后一行出现病名/药名，前一行含「你/是/有/得了」等。
- 修复方向：只在「病名/药名 token 本身跨行断开」时才允许跨行检测（即匹配必须跨越 token 边界），否则按行独立检测；或要求拼接后的匹配区间确实横跨两个 segment 的边界且边界落在词内。

**H-2｜替换窗口取「首个命中前缀」，导致违规片段残留**

- 位置：[compliance.py:264-290](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L264-L290)（`stop` 的取法与左收缩）
- 复现：

```
'你\n有\n抑\n郁\n症'  → '你\n[安全话术]\n症'
'这\n属\n于\n抑\n郁\n症' → '这\n[安全话术]\n症'
```

- 影响：不会留下完整违规句，但输出结构被破坏（安全话术前后残留「你」「症」「疑 似」等片段），在逐字/逐词换行或长空格输入下可见。
- 修复方向：`stop` 不应取「首个命中前缀」，而应取到该句/该行结束（或 run 末尾）；左收缩只用于去掉完全无关的前置 segment，且收缩后必须保证被替换窗口的右边界不被截断在 token 内部。

### 建议改进

- **S-1** 相邻不同类别命中句会丢掉中间换行（`你有抑郁症\n建议服用舍曲林` 合并成一行），建议替换时保留 `newline_before`。
- **S-2** 第三方诊断被误拦：`我有个朋友得了抑郁症`、`医生说他有抑郁症`、`我表姐患上了焦虑症` → `diagnosis`。建议对「我朋友/他/她/医生说」等明确第三方主语放行（或降级为不替换）。
- **S-3** 共情镜像仍有个别误拦：`你有焦虑的情绪`、`你有焦虑的感觉` → `diagnosis`（`post` 是「的」而非「情绪」）。建议把「的 + 情绪/感受/心情/状态」纳入放行后缀。
- **S-4** 流式 `_HOLD_BACK` 按原始字符、规则按 `_squash` 后字符计数；病态空白输入下切点可能落在违规中间，建议保留区按「squash 后 48 字对应的原始长度」动态计算。
- **S-5** 根目录仍散落两份中文文档与 `.brooks-lint-history.json`，违反 `repo-governance.md` §3。
- **S-6** `fallback.py:50,74` 仍 `raise primary_exc`，备用 provider 的真实异常被丢弃，排障误导。
- **S-7** `chat.py:209,245` 各重试 2 次，叠加 `FallbackProvider` 最坏 4 次调用，成本与尾延迟放大。
- **S-8** 内置词仍无法下线（并集），无 `enabled=false` 机制。
- **S-9** 测试缺口：`redline_corpus.py` 未覆盖 `我想死，你了解吗`；无「跨行拼接误拦」与「逐字成行片段残留」用例。建议补 3 条回归用例。

---

## 4. 上线判定

**当前不可上线，剩余 2 条阻断项：**

1. **B-1**：`evaluate` 二次剥离导致 `我想死，你了解吗` 等真实自杀表达漏报，且与 `contains_crisis_terms` 口径不一致。
2. **B-2**：合规仍放行「已抑郁很久了」类诊断结论与部分处方药名，输出侧合规未达标。

已闭环、可作为上线前置项勾销：Redis 超时、成本异常兜底、前端截断提示、依赖拆分与 CI 对齐、上一轮绝大多数危机/合规样本。

建议修复顺序：B-1（一行改动，优先）→ B-2（词表/后缀规则）→ H-1（跨行拼接改为 token 级）→ H-2（stop 取句尾）→ 其余建议项。
