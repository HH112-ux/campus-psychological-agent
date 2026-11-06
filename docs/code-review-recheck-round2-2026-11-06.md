# 第二轮复审报告：整改闭环验证与新增问题

> 复审对象：`docs/code-review-recheck-2026-11-06.md` 所列问题的整改提交（`9e3f94c..84deafd`，共 11 个提交）
> 复审时间：2026-11-06
> 复审基线：`git archive HEAD`（HEAD = `84deafd`）导出的干净快照，不使用工作区
> 复审方式：只读审查 + 干净快照实跑 + 定向绕过实验；未修改业务代码、未提交、未推送、未改 `.env`
> 结论先行：**仍不可上线**。上一轮阻断项 B-1 已关闭，B-2 仅部分关闭；本轮发现 1 个新引入的**危机漏报**（安全红线回归），并确认合规过滤仍有可绕过面与明显误伤。

---

## 0. 方法与证据

- 技能：沿用 `trae-remote-official:code-review-report-plugin:review-code-report` 的证据优先审查标准。按 `docs/repo-governance.md`「文档一律纯 Markdown」，不发布交互式报告，结论落盘为本文。
- 干净快照：

```bash
git archive HEAD | tar -x -C /tmp/recheck2
python3.12 -m venv /tmp/recheck2/backend/.venv
.venv/bin/pip install -r requirements.txt
```

- 实跑输出摘要（全部来自干净快照，非工作区）：

| 命令 | 结果 |
|---|---|
| `python -c "import app.main"` | `import app.main OK` |
| `pkgutil.walk_packages` 全模块导入 | 无失败 |
| `ruff check .` | `All checks passed!` |
| `pytest -q` | **291 passed, 1 skipped**（skip 为未设置 `REDIS_TEST_URL` 的真 Redis 集成用例） |
| `py_compile` 全部 `scripts/*.py` | 无失败 |

- 工作区状态：代码文件无未提交改动（仅 `CHANGELOG.md`、`README.md`、`docs/improvement-roadmap.md` 与若干未跟踪文档），可判定 **HEAD 就是可部署状态**。
- 关键对比实验：把 `chat.py` 的 `get("type")` 手工还原为 `get("emotion")` 后重跑用例 → `1 failed`；恢复后 `21 passed`（证明新用例有效）。

---

## 1. 逐条核对上一轮结论

| 上一轮问题 | 判定 | 依据 |
|---|---|---|
| B-1 HEAD 不自洽、缺 13 个模块、ratelimit 旧名 | **已关闭** | 13 个模块均在 HEAD 树中；干净快照 import/ruff/pytest 全绿；`shared_state_backend` 通过 `AliasChoices` 兼容旧名 `ratelimit_backend` |
| B-2 输出侧合规过滤可绕过 | **未关闭（部分修复）** | 上一轮 4 个样本已拦截；但「你患上了抑郁症」「你可能抑郁了」「这属于抑郁症」等仍原样透传 |
| B-2 的 200 字切分漏检 | **已关闭** | 48 字保留区 > 规则最大跨度（实测 35）；跨切点实验无漏检 |
| chat.py:174 取错键 | **已关闭** | 改为 `get("type")`；还原旧行用例必失败 |
| H-1 流式静默截断 / 无心跳 / 断连丢回复 | **已关闭** | 心跳实测按间隔下发；`done.truncated` 与 `degraded` 同时置位；断连落库用例通过 |
| H-2 危机误报 | **已修复误报，但引入更严重的漏报** | 「今天累到不想动了」「我想死你了」→ none；但「我想死，你能帮帮我吗」→ none |
| H-3 DB 词库整体替换 | **已关闭** | 改为并集；`test_db_lexicon_merges_with_builtin` 通过 |
| H-4 求助电话校验范围 | **未变** | 仍只校验内置常量与格式；号码真实性仍无法从代码验证 |

### 1.1 HEAD 自洽性（B-1）

- HEAD 树中已包含：`app/core/{cost,counter,llm_json,metrics,redis_client,text}.py`、`app/db/user_data_registry.py`、`app/llm/{router,qwen,fallback}.py`。
- `git ls-tree` 确认全部入库；工作区无未提交的代码文件。
- `ratelimit.py` 与 `main.py` 均读 `shared_state_backend`，[config.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/config.py#L62-L64) 用 `AliasChoices("shared_state_backend", "ratelimit_backend")` 兼容旧配置。
- **判定：通过。** 上一轮的 84 个测试失败在当前 HEAD 已不存在（291 passed）。

### 1.2 合规 48 字保留区

- [compliance.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L112-L116) 已移除 `_MAX_BUFFER=200`，改为「只在句末标点切分；无标点时保留末尾 48 字」。
- 规则最大匹配跨度实测（脚本穷举各分支最大字段长度）：

| 规则 | 最大跨度 |
|---|---|
| `_DIAGNOSIS` | **35**（`ta的症状` + 10 + `倾向于` + 6 + `疑似患有` + `创伤后应激障碍`） |
| `_EFFICACY` | 8 |
| `_DRUGS_RE` | 6 |
| `_STOP_ADVICE_RE` | 4 |

35 < 48，且违规匹配不允许跨句末标点/换行，因此「跨切点的违规句必然整体落在保留区」的论证成立。
- 流式实验：对 49–299 字的所有长度、逐字喂入与单块喂入，违规句均被拦截；多短句拼接 `["你有","抑郁","症。"]` 被拦截；同一回复同类安全话术只插入 1 次。
- **判定：通过。** 但该不变量依赖「规则不跨换行、且跨度 < 48」这一隐含前提，建议加一条自动测量最大跨度的回归测试，避免后续加规则时静默失效。

### 1.3 chat.py:174 取键与用例有效性

- [chat.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L172-L176) 已改为 `.get("type")`。
- 手工还原为 `.get("emotion")` 后：`FAILED tests/test_cost_routing.py::test_build_messages_reads_emotion_type_for_routing`；恢复后 `21 passed`。
- **判定：通过。** 用例确实覆盖了该分支，不是「绿着过」。

### 1.4 危机误报收窄与否定/夸张剥离

实跑（`crisis.evaluate` + 内置词表）：

| 样本 | 结果 | 期望 | 结论 |
|---|---|---|---|
| 今天累到不想动了 | none | none | 通过 |
| 我想死你了 | none | none | 通过 |
| 我想死 | high | high | 通过 |
| 我不想活了 | high | high | 通过 |
| 我不想死，但也不想活了 | high | high | 通过 |
| 我没想自杀，但活不下去了 | high | high | 通过 |
| 我不想死，可是活着好累 | mid | mid | 通过 |

- DB 词库并集：[crisis.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L95-L99) 为 `set(内置) | set(DB)`；运营写入任意词后内置「想死」仍在生效（用例 `test_db_lexicon_merges_with_builtin` 通过）。
- **但发现新的漏报路径（阻断项，见 2.1）**：剥离用的是归一化后的纯子串替换，`想死你` 会把「我想死，你能帮帮我吗」整段吃掉。

### 1.5 SSE 健壮性

- 心跳：[messages.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/api/routes/messages.py#L35-L71) 用队列 + `wait_for(timeout=interval)` 中继，默认 5s（[config.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/config.py#L106-L107)）。以 0.1s 间隔实测：

```
[(0.1,'ping'),(0.2,'ping'),(0.3,'ping'),(0.4,'ping'),(0.51,'ping'),(0.55,'delta'),(0.55,'done')]
```

  帧序正确，ping 不早于/晚于业务帧。
- 慢首包：5s < 小程序 idle 10s（[sse.js](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/utils/sse.js#L70)），且 `onChunkReceived` 每次重置计时；ping 帧无业务分支，前端忽略，不会被误解析。
- 截断：[chat.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L342-L354) 抛 `_StreamTruncated` → `truncated=True, degraded=True`，`done` 帧带 `truncated`；前端 [chat.wxml](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/pages/chat/chat.wxml#L39) 用 `degraded` 展示「连接不稳定，已为你保留」。
- 断连落库：[chat.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L394-L402) 的 `finally` 用后台任务收尾；`test_disconnect_still_persists_generated_content` 通过（assistant 消息已解密校验）。
- 相关用例：`test_stream_midway_failure_keeps_partial_and_marks_truncated`、`test_stream_emits_heartbeat_while_waiting`、`test_stream_internal_failure_sends_error_frame`、`test_disconnect_still_persists_generated_content` → **4 passed**。
- **判定：通过。** 唯一遗留：`done.truncated` 字段前端未单独使用（靠 `degraded` 兜底），属提示语义不够精确，非功能缺陷。

---

## 2. 新引入的问题

### 2.1 阻断｜危机检测被「想死你」前缀剥离击穿（安全红线回归）

- 位置：[crisis.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L42-L55)（`_SAFE_CONTEXT_PATTERNS` 第 44 行含裸词 `"想死你"`、`"想死你们"`；`strip_safe_context` 对**归一化后**文本做纯子串 `replace`）
- 关联：同一函数被 [long_memory.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/long_memory.py#L216) 的确定性兜底复用；`chat.py:195` 的记忆抽取门槛也依赖它判出的 `crisis.level`。
- 实测：

| 用户输入 | 归一化 | 剥离后 | 判定 |
|---|---|---|---|
| 我想死，你能帮帮我吗 | 我想死你能帮帮我吗 | 我能帮帮我吗 | **none** |
| 我想死，你说我该怎么办 | 我想死你说我该怎么办 | 我说我该怎么办 | **none** |
| 我想死，你要好好的 | 我想死你要好好的 | 我要好好的 | **none** |
| 我想死，你们别管我 | 我想死你们别管我 | 我们别管我 | **none** |
| 我想死 | 我想死 | 我想死 | high（正常） |

- 影响：真实自杀表达被判定为 `none` → 不下发危机卡片/热线、不推值班告警、`crisis_score` 不累计；同时 `_schedule_memory_extraction` 会照常触发，`extract_and_save` 的兜底又因同一函数返回空而放行，**危机内容可能写入长期记忆**。这同时违背「危机内容禁入长期记忆」的既有验收项。
- 触发条件：`想死` 后紧跟 `你/你们/您`（归一化会吞掉中间的逗号、句号、空格、换行），例如「我想死，你能…」「我想死，你们…」。这是求助类消息的高频句式。
- 回归性质：整改前 `想死` 直接命中 L1，此句为 high；本次为消除「我想死你了」误报而引入，属**新引入的漏报**。
- 修复方向（任一）：
  1. 在**原文**上剥离（保留标点），再归一化匹配——「想死，你」不会命中「想死你」；
  2. 只保留完整寒暄形态（`想死你了`、`想死我了`、`想死您了`），删除裸前缀 `想死你`/`想死你们`，或改为带边界的正则（要求后接句末/语气词）；
  3. 为「L1 命中但被剥离」增加一条独立判定：若剥离前命中一级词，至少降级为 mid 并要求模型确认，不允许直接 none。
- 建议同时补用例：`我想死，你能帮帮我吗`、`我想死，你们别管我` 必须为 high。

### 2.2 阻断｜合规过滤仍未闭环（B-2 部分修复）

- 位置：[compliance.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L52-L91)
- 上一轮的 4 个样本已全部拦截（`你有抑郁症`、`你可能是抑郁症`、`这听起来像焦虑症`、`你的情况是中度抑郁`、`可以试试百忧解`）。
- 但仍可原样透传的常见表述（实测 `detect()` 返回 `None`）：

| 输入 | 期望 | 实测 |
|---|---|---|
| 你患上了抑郁症 | 拦截 | **透传** |
| 你可能抑郁了 | 拦截 | **透传** |
| 你抑郁了 | 拦截 | **透传** |
| 这属于抑郁症 | 拦截 | **透传** |
| 建议服用 SSRI 类药物 | 拦截 | **透传** |
| 吃点氟哌啶醇吧 | 拦截 | **透传** |
| 可以试试坦度螺酮 | 拦截 | **透传** |
| 用点奥沙西泮 | 拦截 | **透传** |

- 根因：
  - 分支 2 只允许「弱判断动词 + **明确病名**」，裸病名必须走分支 3/4，而分支 3 要求 `是/有`、分支 4 要求分度词，导致「你可能抑郁了」「你抑郁了」落空；
  - `_ASSERTIVE` 未收录「患上/患上 了」这类写法；
  - 「这属于…」缺少无主语 + `属于` 的分支（分支 5 只认 `听起来/看起来/感觉/似乎`）；
  - `_DRUGS` 未收录 SSRI、氟哌啶醇、坦度螺酮、奥沙西泮。
- 影响：面向学生的产品仍可能输出诊断口吻与处方药名，属合规验收未达标。
- 修复方向：把「裸病名」的判定从「必须有是/有或分度词」改为「人称 + 任意判断/推断/程度词 + 裸病名」并单独维护一份「正常化共情」白名单；补 `患上|得了|属于` 与药品类名/通用名；对 `SSRI/SNRI` 等类别词单独拦截。

### 2.3 高风险｜合规规则扩充造成共情话术误伤

实测 17 条正常/半正常话术，8 条被整句替换：

| 输入 | 命中类别 | 实际下发 |
|---|---|---|
| 你有点焦虑 | diagnosis | 我不能给出诊断，具体需要专业医生评估。 |
| 你有些焦虑 | diagnosis | 同上 |
| 你看起来有些焦虑 | diagnosis | 同上 |
| 你最近是不是有点焦虑 | diagnosis | 同上 |
| 你是不是有点焦虑 | diagnosis | 同上 |
| 感觉你最近挺焦虑的 | diagnosis | 同上 |
| 你好像有点抑郁 | diagnosis | 同上 |
| 你一定会好起来的，我相信你 | efficacy | 我没法保证效果，具体进展需要专业评估。 |

- 影响：这是一个「温暖陪伴」定位的产品，模型最自然的共情镜像句（「你有点焦虑」「你一定会好起来的」）会被替换成临床免责声明，对话连贯性和温度被破坏；用户可能感到被突然「官方化」。
- 说明：
  - 「你有点焦虑」类属**本次新增**（旧规则只认 `就是/属于/患有/…` + 明确病名）。
  - 「你一定会好起来的」属**旧规则遗留**（`_EFFICACY` 首分支未变），但同样应处理。
  - 反向漏报：`坚持吃药就会好起来`、`你一定会慢慢好起来的` 反而不拦截，说明疗效规则「宁可误伤常用安慰、却放过真实疗效断言」，口径不一致。
- 修复方向：诊断类别只保留「结论性」句式（明确病名 + 断言/分度/推断），把「有点/有些 + 裸情绪词」列为正常化共情放行；疗效类别改为「承诺性」语义（保证/一定/百分百 + 治愈类结果），放行「会好起来」这类祝福语；补 `就会好起来` 等真实断言。

### 2.4 建议改进｜其余新问题

| 编号 | 位置 | 问题 | 影响/触发 | 修复方向 |
|---|---|---|---|---|
| S-1 | [redis_client.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/core/redis_client.py#L24-L26) | `from_url` 未设置 `socket_connect_timeout` / `socket_timeout`（redis-py 默认 None） | Redis 网络黑洞时，所谓「fail-open」会先长时间阻塞，限流/告警/计数把主链路拖慢 | 显式设置 1–2s 连接与读写超时，再走 fail-open |
| S-2 | [cost.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/core/cost.py#L30-L47) | docstring 称「任何异常均不应影响主链路」，但函数体无 try/except | 若 `get_settings()`/日志异常，成本统计会向上抛出，影响回复 | 用 try/except 包住累计与日志 |
| S-3 | [compliance.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/compliance.py#L52-L78) | 规则不允许跨 `\n`；`你可能是抑 郁症`、`你有抑\n郁症`、`你 患 上 了 抑 郁 症` 均透传 | 模型输出带换行/空格断词时漏检（低频） | 检测前先做「去空白再匹配」，或对断词做宽松匹配 |
| S-4 | [chat.js](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/pages/chat/chat.js#L351-L353) | `done.truncated` 未被前端使用，仅靠 `degraded` | 截断与普通降级提示相同，未区分「保留半句」 | 前端读取 `truncated` 给出更准确文案 |
| S-5 | 仓库根目录 | 两份中文文档与 `.brooks-lint-history.json` 仍未跟踪且散落根目录 | 违反 `repo-governance.md` §3 根目录清洁 | 移出根目录或入库到 `docs/` |
| S-6 | [requirements.txt](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/requirements.txt) | 生产镜像 `Dockerfile` 直接安装含 `pytest`/`ruff` 的同一份清单 | 生产镜像增大、携带测试工具 | 拆分 `requirements-dev.txt` |
| S-7 | [crisis.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L95-L99) | 并集后运营**无法下线**任何内置词 | 若某内置词成为误报源，只能改代码发版 | 增加 `enabled=false` 的内置词禁用表（白名单机制），并保留红线不可禁用 |
| S-8 | [fallback.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/llm/fallback.py#L70-L74) | 备用流式已产出后失败时 `raise primary_exc`，会丢失备用异常与真实原因 | 排障时误导为「主 provider 故障」 | 记录备用异常链后再抛，或抛统一 `FallbackError` |
| S-9 | [chat.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L209-L221) | `_generate_nonstream` 自身重试 2 次 + `FallbackProvider` 容灾，最坏 4 次调用 | 成本与尾延迟放大（非正确性问题） | 明确重试层数，避免重复放大 |

---

## 3. 新增模块与依赖清单结论

### 3.1 新增 13 个模块

| 维度 | 结论 |
|---|---|
| 多模型容灾回退条件 | 合理：仅「主 provider 未产出任何 chunk」时切备；已产出则保留并抛截断，避免两段回复硬拼。瑕疵见 S-8 |
| 成本统计正确性 | 基本正确：按 tier 累计次数/提示字符/生成字符；重试与截断路径只记一次；进程内累计已在文档声明。瑕疵见 S-2 |
| Redis 缺失降级 | 语义正确（限流 fail-open、告警冷却放行、计数返回 0），但缺少连接/读写超时，可能从「快速失败」退化为「长时间阻塞」，见 S-1 |
| 其他 | `counter`/`metrics` 的双后端抽象清晰；`text`/`llm_json` 消除重复实现；`user_data_registry` 有覆盖测试；`qwen` 与 `zhipu` 接口平行 |

### 3.2 requirements.txt

- Python 3.12 全新 venv 安装成功，`import app.main`、全模块导入、`ruff`、`pytest`（291 passed / 1 skipped）全部通过 → **可复现**。
- 无隐式依赖：`scripts/*.py` 仅用标准库与 `app.*`，全部可编译。
- 版本钉死：全部 `==` 锁版本，与 `Dockerfile`（`python:3.12-slim`）及 `requires-python >=3.12` 一致（`counter.py` 使用了 PEP 695 泛型语法，必须 3.12+，当前一致）。
- 唯一问题：测试/质量工具混入生产依赖清单（S-6）。

---

## 4. 问题清单（按严重度）

### 阻断上线

**B-1（上轮）已关闭**：HEAD 自洽、可安装、可导入、测试全绿。

**B-2（上轮）未关闭**：见 2.2。`你患上了抑郁症`、`你可能抑郁了`、`这属于抑郁症`、`建议服用 SSRI 类药物` 等仍原样透传。

**B-3（本轮新增）危机漏报回归**：见 2.1。`我想死，你能帮帮我吗` 等真实求助被判 `none`，且可能进入长期记忆。
- 位置：`backend/app/services/crisis.py:42-55`（第 44 行）、`backend/app/services/long_memory.py:216`、`backend/app/services/chat.py:195`
- 影响：危机卡片/热线/值班告警全部不触发；危机内容可能被长期留存
- 触发：`想死` 后紧跟 `你/你们/您`（归一化会吞掉标点）
- 修复方向：见 2.1 三条

### 高风险

1. **H-A 合规误伤共情话术**：见 2.3。`你有点焦虑`、`你看起来有些焦虑`、`你一定会好起来的` 等被整句替换，核心体验受损。
2. **H-B 求助电话仍未闭环**（上轮 H-4 未变）：`0757-23456789` 真实性无法从代码验证；数据库权威资源表仍只做格式校验。上线前需校方书面确认并补数据库侧校验。
3. **H-C Redis 客户端无超时**：见 S-1。生产 Redis 网络异常时可能拖慢主链路，与「fail-open 不阻断对话」的设计目标不符。

### 建议改进

- S-2 成本统计异常兜底
- S-3 合规跨换行/空格断词
- S-4 `truncated` 前端未区分展示
- S-5 根目录清洁（治理）
- S-6 生产依赖清单拆分
- S-7 内置词禁用机制
- S-8 fallback 异常链
- S-9 重试层数叠加
- 另建议新增「规则最大匹配跨度」自动回归测试，防止未来规则超过 `_HOLD_BACK=48` 时静默失效。

---

## 5. 上线判定

**不可上线。** 阻断项：

1. **B-3（新）**：危机检测漏报回归，属安全红线一票否决，必须修复并补「求助句式」正例。
2. **B-2（旧，未闭环）**：合规过滤仍放行常见诊断/用药表述，输出侧合规验收未达标。
3. **H-B（旧）**：求助电话真实性需校方书面确认，属外部依赖，无法仅靠代码关闭。

已关闭、可作为上线前置项勾销：B-1（HEAD 自洽）、48 字保留区切分漏检、`chat.py` 取键、H-1（心跳/截断/断连落库）、H-3（词库并集）。

修复优先级建议：B-3 → B-2 → H-A → H-C → 其余。
