# 整改复审报告：2026-11-06 两批修复的真实性与回归检查

> 复审对象：`docs/code-review-2026-11-06.md` 所列 3 个阻断项与高风险项对应的两批整改提交
> 复审时间：2026-11-06
> 复审基线：当前工作区（含未提交改动）+ 提交历史（HEAD = `9e3f94c` 之后的 docs 提交）
> 复审方式：只读代码审查 + 本地实测 + git 对象比对 + 两名独立校验者交叉复核
> 结论先行：**当前状态不可上线**。代码层面多数修复真实生效，但**版本库中的提交状态无法导入运行**，且**输出侧合规过滤未达成验收目标**。

## 0. 审查方法与所用技能

- 技能：使用 `trae-remote-official:code-review-report-plugin:review-code-report`（已加载其审查标准并按证据优先原则执行）。因本项目 `docs/repo-governance.md` 要求文档一律纯 Markdown 入库、不生成交互式页面，故未发布交互式卡片报告，改为落盘本 Markdown 报告。
- 本地实测：`ruff check backend` 全绿；`pytest -q` → **245 passed, 1 skipped**；`node --check` 全量小程序 JS 通过。
- 独立复核：两个独立校验 agent 逐条核对候选问题，均确认下文 B-1、B-2、H-1~H-4 等结论（行号与复现结果一致）。
- 关键反证实验：`git archive HEAD` 导出干净快照后执行 `python -c "import app.services.chat"`，**导入失败**（详见 B-1）。

## 1. 结论摘要

| 项 | 判定 | 一句话结论 |
|---|---|---|
| 1. 敏感字段加密 | 代码层通过，交付层未通过 | 4 个字段写入均加密、读取均解密，无遗漏写入点；但依赖模块未入库导致提交不可运行；`risk_events.matched` 无测试 |
| 2. Mongo 认证与暴露面 | 通过 | `--auth` 生效、不再发布 27017、生产缺凭据拒绝启动 |
| 3. 危机内容禁入长期记忆 | 通过 | mid/high 双层拦截 + 与提示词无关的确定性兜底；但兜底会误杀日常口语，且测试无误杀用例 |
| 4. HTTPS | 代码层通过，待环境实测 | 443 唯一业务入口、80 仅跳转、证书缺失即失败；模板渲染未转义，config 层无 TLS 校验 |
| 5. 求助电话 | 部分通过 | 代码中已无 `0XX` 占位；但只校验格式与内置常量，不校验数据库权威表，号码真实性无法从代码验证 |
| 6. 输出侧合规过滤 | **未通过** | 多个常见诊断/用药表述可直接透传；200 字符切分会切断违规句；流式与合规组合存在延迟与重复插入 |
| 7. SSE 真流式 | 真流式通过，健壮性部分通过 | 确认边生成边下发、无重复推送；但无心跳、客户端 10s 与服务端 30s 不匹配、中途失败静默截断、断连丢回复 |

## 2. 逐项验证

### 2.1 敏感字段加密：代码层通过，交付层不通过

**写入（已加密）**

- `emotion_records.evidence` / `messages.emotion.evidence`：`backend/app/services/emotion.py:219-243`，同一份密文写两处。
- `checkins.note`：`backend/app/services/checkins.py:55`。
- `risk_events.matched`：`backend/app/services/crisis.py:137`。
- 全局搜索（含 `backend/scripts/`、seed、迁移）未发现其他明文写入这些字段的路径；`seed_crisis.py` 只写危机词库与资源，不涉及敏感原文。

**读取（均已解密）**

- 会话详情 / 消息：`backend/app/services/sessions.py:108,116`
- 日志时间线：`backend/app/services/emotion_logs.py:109,126`
- 打卡：`backend/app/services/checkins.py:40,130`
- 数据导出：`backend/app/services/privacy.py:107-143`
- 坏例抽样：`backend/app/services/bad_cases.py:24,61-63`

**提示词链路无密文泄漏**：`latest_session_emotion()`（`emotion.py:257-265`）返回的对象含密文 `evidence`，但 `prompts.py` 只取 `type`/`intensity`，未进入提示词。

**迁移脚本**（`backend/scripts/migrate_encrypt_sensitive_fields.py`）

- 幂等：`is_encrypted()` 前置判断，可重复执行。
- 缺密钥：`main()` 明确拒绝执行并返回，不会误跑。
- 存在问题：docstring（第 16 行）声称按 batch 分批，实际无 `--batch-size` 参数、无分批；失败分支只 `return`，**进程退出码仍为 0**（第 104-130 行），无法用于自动化发布门禁；`_verify_sample()` 只抽查 `emotion_records`。

**缺口**

- `risk_events.matched` 没有任何加密断言测试（tests 中无 `matched` 加密用例），属回归防护缺口。
- 新增派生副本 `sessions.title = text[:12]`（`backend/app/services/chat.py:135`）以明文保存用户首句片段。由于 `messages.content` 本身未在本次加密范围内（设计如此），该副本不构成“额外泄漏”，但与“敏感文本加密落库”的口径不一致，建议明确豁免或同等处理。

### 2.2 Mongo 认证与暴露面：通过

- `backend/docker-compose.yml`：mongo 使用 `--auth`，仅 `expose`，**不再发布 27017**；api 通过 `depends_on: condition: service_healthy` 等待副本集/健康检查。
- `backend/app/config.py:169-175`：生产缺 `DATA_ENCRYPTION_KEY`、或 `MONGODB_URI` 不含用户名/密码时拒绝启动。
- 残余小问题：nginx 对 api 只有 `depends_on` 无健康条件，冷启动瞬间可能短暂 502（不影响安全）。

### 2.3 危机内容禁入长期记忆：通过（含误杀副作用）

- 门槛覆盖 mid 与 high：`backend/app/services/chat.py:193`。
- 存在与提示词无关的确定性兜底：`backend/app/services/long_memory.py:192,216` 调用 `core/text.py` 的 `contains_crisis_terms()`，只依赖词库，不依赖模型是否听话。
- 兜底测试：`backend/tests/test_long_memory.py` 覆盖“模型仍返回记忆时也被丢弃”。
- **误杀**：兜底使用 L1+L2 全量词表，L2 含「累到不想动」「不想动了」「没人在乎」等日常口语（`crisis_data.py:39-47`）。实测「今天累到不想动了」命中 2 条，导致该轮**完全不抽取记忆**。只影响记忆召回、不阻断对话，可接受但需知情。
- 测试缺口：没有“正常内容不被误杀”的负向用例。

### 2.4 HTTPS：代码层通过，环境待实测

- `backend/nginx/nginx.conf.template:76-84`：443 为唯一业务入口；`:60-69` 的 80 仅 301 跳转（保留明文 `/health` 供探活）。
- `backend/nginx/docker-entrypoint.sh:20-22`：模板/证书/私钥缺失即 `fail` 退出；`:30` 再执行 `nginx -t`，不会静默降级。
- **模板渲染注入风险**：`entrypoint.sh:24-27` 的 `sed` 替换完全未转义。若 `TLS_SERVER_NAME`/路径含 `|`、`&` 或换行，会导致替换失败或注入额外指令。该值由运维在部署时提供，非用户输入，风险等级为中。
- `config.py` 没有任何 TLS 校验，HTTPS 完全依赖 nginx 侧兜底；`TLS_SERVER_NAME` 若为默认 `_`，将接受任意 Host。
- 域名、证书、微信 request 域名白名单属于外部依赖，本地无法验证，上线前必须实测。

### 2.5 求助电话：部分通过

- 代码中已无 `0XX`/`XXXX` 占位（仅历史文档留有记录，属历史留档）。
- `backend/app/services/crisis_data.py:68-75` 现值为：`12356`、`400-161-9995`、`12355`、`0757-23456789`。
- 校验逻辑：`config.py:179` 调用 `phone_problems()`，**只校验格式**，且**只覆盖内置常量**；数据库 `crisis_resources` 为权威源（`crisis.py:229-239`），写入空号/占位号仍可正常启动。
- **真实性无法从代码验证**：`0757-23456789` 呈明显顺序数字特征，代码注释称“校方提供”。这是安全关键信息，上线前必须取得校方书面确认，并同步校验数据库中的号码。

### 2.6 输出侧合规过滤：未通过

`backend/app/services/compliance.py:34-51` 的检测规则覆盖面不足，实测（直接调用 `sanitize`）：

| 输入 | 结果 | 期望 |
|---|---|---|
| `你有抑郁症` | 原样通过，`hits=[]` | 应拦截 |
| `你可能是抑郁症` | 原样通过，`hits=[]` | 应拦截 |
| `这听起来像焦虑症` | 原样通过，`hits=[]` | 应拦截 |
| `你的情况是中度抑郁` | 原样通过，`hits=[]` | 应拦截 |
| `可以试试百忧解` | 原样通过，`hits=[]` | 应拦截（品牌名未收录） |
| `你这是典型的抑郁症。` | 正确替换 | — |
| `建议服用舍曲林` | 正确替换 | — |

- 根因：`_DIAGNOSIS` 仅识别「就是/属于/患有/患了/得了/确诊为/诊断为/是」，缺「有/可能/听起来像/轻度/中度」；`_DISORDERS` 只有“抑郁症”，不含“抑郁”；`_DRUGS` 未覆盖常见品牌名。
- **切分漏检**：`OutputGuard`（`compliance.py:102-115`）在 `_MAX_BUFFER=200`（`:60`）处强制放行。实测 `198*"a" + "你这"` 与 `"是抑郁症。"` 两段均不命中，完整违规句被拆开后**原样下发且无法回收**。
- **流式语义退化**：`sanitize()` 的 `inserted` 是函数局部变量（`:79`），`OutputGuard` 每次 `feed` 重新调用，导致同一条回复内同类违规会**重复插入**安全文案；非流式只插入一次，两种模式产出不一致。
- **短回复阻塞**：无标点且不足 200 字的回复会一直留在 `_buf`，直到 `flush()` 才一次性下发，真流式的“打字感”完全失效。
- 误伤转述（低）：实测「如果医生诊断你为抑郁症呢」整句被替换，安全性可接受但削弱倾听感。

### 2.7 SSE 真流式：真流式通过，健壮性部分通过

- 真流式确认：`chat.py:239-254` 逐块 `yield`，`zhipu.py:70-82` / `qwen.py:83-95` 逐行解析 SSE，`fallback.py:52-74` 透传，非“先收齐再推”。
- 帧约定与前端一致：`meta/delta/crisis/emotion/done/error`，前端 `sse.js`、`chat.js` 均按此解析；`X-Accel-Buffering: no` 已设置。
- 无重复推送：`_stream_deltas` 仅在 `produced == 0` 时抛错重试，已产出后失败直接 `return`，不会重发已发送内容。
- **静默截断**：`chat.py:247-250` 在已产出后异常时直接 `return`，`degraded` 保持 False、无日志、无标记，用户看到半句但界面按“正常结束”收尾。
- **心跳缺失 + 超时不匹配**：无 `ping` 帧；客户端 idle 10s（`miniprogram/utils/sse.js:70`），服务端模型读超时 30s（`config.py`），首包慢于 10s 会被前端误判失败并中止。
- **断连丢回复**：Starlette 在客户端断开时取消生成器，`chat.py` 的 `_finalize` 不会执行——用户消息已落库、assistant 回复与 rounds 均缺失，记忆抽取也跳过。

## 3. 修复引入的新问题

### 3.1 加密是否破坏既有查询：未发现

- `backend/app/db/indexes.py` 没有针对 `evidence`/`note`/`matched` 的索引或唯一约束。
- 各 service 没有按这些字段做匹配、去重或聚合；`long_memory` 的 `content_hash` 在加密前基于明文计算，去重不受影响。
- 唯一新增的明文副本是 `sessions.title`（见 2.1），不破坏查询。

### 3.2 流式 + 合规守卫组合

- 内容截断：会（静默截断，无标记）。
- 重复：正文不会重复推送；但**安全文案会重复插入**（`inserted` 每次重置）。
- 阻塞：生成不阻塞，但**展示会阻塞**（短无标点回复等到 flush）。
- 其他：断连丢回复、无心跳、错误帧后前端需等 10s 才收尾。

### 3.3 小程序四项修复：未引入新问题

- 外部类（`5116a5c`）：`externalClasses: ['inline-card']` + 根节点 `class="... inline-card"`，父组件以 `inline-card="inline-card"` 传入，用法正确；未传外部类的场景只是无效类名，无副作用。
- 情绪文字对比度（`1b32989`）：新增 `--emo-text` 复用已存在的语义令牌，`app.wxss` 中 `--success/--info/--danger/--warn/--text-2` 均有定义，不存在“令牌未定义导致颜色失效”的隐患；实测对比度约 4.96~5.76:1，达 WCAG AA。
- 字数边界（`477f235`）：`maxlength="-1"`，2000 可发送、2001 禁用，边界可达，逻辑自洽。
- crisis-card data 合并（`9e3f94c`）：`_items` 与 `visible` 同步更新，无状态错位。
- 遗留（既有）：`crisis-card.js` 只过滤 `X`，若数据库下发 `0XX` 类无效号仍会展示。

### 3.4 提交是否夹带无关改动：是

- `2ef94b9`（主题：长期记忆）夹带了 E3 情绪路由改动（`chat.py` 30 行），并**引入缺陷**：`chat.py:174` 取 `.get("emotion")`，而 `latest_session_emotion()` 返回的键是 `type/intensity/evidence/risk_level`，该值恒为 `None`，重情绪分流永不生效（详见 M-1）。
- `7035431`（主题：SSE 流式）夹带了 256 行 `tests/test_cost_routing.py`（E3 测试），但 E3 的生产实现（`router.py`、`cost.py`、`fallback.py`、`llm/__init__.py` 改动）**未提交**——这正是 B-1 的直接成因。
- 工作区另有 17 个已修改文件、21 个未跟踪文件（E2/E3 相关模块）未提交；根目录还散落两份中文文档，违反 `repo-governance.md` §3 的根目录清洁要求。

## 4. 问题清单（按严重度）

### 阻断上线

**B-1 版本库状态不自洽，整改成果未入库，HEAD 无法启动**

- 位置：`backend/app/services/chat.py:28,36`、`backend/app/services/privacy.py:33`、`backend/app/services/emotion.py:25-30`、`backend/app/services/crisis.py:16`、`backend/app/services/long_memory.py:27-33`、`backend/app/main.py:27`
- 缺失模块：`app/core/cost.py`、`app/core/counter.py`、`app/core/llm_json.py`、`app/core/metrics.py`、`app/core/redis_client.py`、`app/core/text.py`、`app/db/user_data_registry.py`、`app/llm/router.py`、`app/llm/qwen.py`、`app/llm/fallback.py`（全部仅存在于工作区未跟踪文件）
- 影响：从 `4db568e` 起的提交开始，全新克隆、CI 与容器构建均 `ImportError`，无法启动；当前“可运行”只存在于本地未提交工作区，线上无法复现审查结论。
- 触发：任何基于 git 的构建/部署/CI。
- 修复方向：把未跟踪模块与已改文件按逻辑拆成独立 PR 提交；每个提交保证 `ruff + pytest + import` 自绿；CI 增加 import smoke test（`python -c "import app.main"`）。

**B-2 输出侧合规过滤未达成验收目标，常见表述可直接透传**

- 位置：`backend/app/services/compliance.py:34-51`（规则）、`:60,102-115`（切分）
- 影响：面向学生的产品可能输出诊断结论（“你有抑郁症”“中度抑郁”）与非处方药推荐（“百忧解”），属合规风险；200 字符切分可使违规句被拆分后原样下发且不可撤回。
- 触发：模型使用“有/可能/听起来像/轻中度”等高频表述，或违规句跨越 200 字无标点区段。
- 修复方向：改用“意图+实体”双层规则（疾病名词表 + 判断/推断动词表，覆盖“有/可能/像/倾向/轻中重度”）；药品表补品牌名；流式改为按标点或固定小窗口（如 40 字）切分并在下发前保留 1 句回看窗口，避免跨块漏检。

### 高风险

**H-1 流式静默截断与断连丢回复**

- 位置：`backend/app/services/chat.py:239-254`（截断）、`:296-364`（无心跳、`_finalize` 在生成器内）
- 影响：已看到半句的用户会被当作“正常结束”；客户端 10s 空闲超时小于服务端 30s，首包慢即误判失败；断连时用户消息已入库、回复与 rounds 缺失。
- 触发：模型中途超时/网络抖动、首 token >10s、用户切页或弱网。
- 修复方向：`produced>0` 时也置 `degraded` 并在 `done` 帧带 `truncated`；增加 5s 级 `ping` 帧；在开流时先落一条 assistant 占位消息并分段更新，或把 `_finalize` 放到独立任务中 shield。

**H-2 危机检测误报为 high（既有，非本次引入，但与记忆兜底同源）**

- 位置：`backend/app/services/crisis_data.py:39-54`、`backend/app/services/crisis.py:100-115`
- 实测：`今天累到不想动了` → **high**（2 条 L2 命中 = 4 分达到阈值）；`我想死你了` → **high**（L1“想死”）
- 影响：日常口语触发固定危机话术、跳过模型回复，并推送高风险通知给值班人；同时导致该轮记忆不抽取。
- 修复方向：L2 去重（重叠词只算一次）、加入语境/否定判断、区分“生理疲惫”与“心理绝望”，并对“想死你了”这类寒暄做白名单。

**H-3 数据库词库整体替换内置词表（既有，上轮 H4 未修）**

- 位置：`backend/app/services/crisis.py:63-64`（`l1 = sorted(set(l1 or LEVEL1_PHRASES))`）
- 影响：运营在数据库写入任意少量词，就会使内置红线词整体失效，危机召回直接坍塌；新加的确定性记忆兜底同样依赖该词库。
- 修复方向：改为“内置 + 数据库增量合并”，只允许追加，不允许替换。

**H-4 求助电话校验只覆盖内置常量**

- 位置：`backend/app/config.py:179`、`backend/app/services/crisis_data.py:95`、`backend/app/services/crisis.py:229-239`
- 影响：数据库权威资源表里配置空号/占位号仍可通过启动校验；`0757-23456789` 的真实性无法从代码验证。
- 修复方向：启动时对数据库资源做一次同样校验；上线前向校方书面确认号码；必要时加“占位/顺序数字”识别规则。

### 建议改进

- **M-1** `backend/app/services/chat.py:174`：`.get("emotion")` 应改为 `.get("type")`，否则 E3 重情绪路由永不生效（由 `2ef94b9` 夹带引入）。
- **M-2** `backend/app/services/compliance.py:79,102-123`：`inserted` 应在 `OutputGuard` 生命周期内共享，避免同回复重复插入安全文案；短无标点回复建议按长度窗口渐进下发。
- **M-3** `backend/scripts/migrate_encrypt_sensitive_fields.py:104-130`：失败应 `sys.exit(1)`；补分批与 `checkins`/`messages` 校验；修正 docstring 与实际能力不符。
- **M-4** `backend/nginx/docker-entrypoint.sh:24-27`：`sed` 替换前对 `|`、`&`、换行做转义或改用 `envsubst`；`TLS_SERVER_NAME` 增加非空/非 `_` 校验。
- **M-5** `backend/docker-compose.yml`：nginx 对 api 增加 healthcheck 依赖，避免冷启动 502。
- **S-1** 为 `risk_events.matched` 增加加密断言测试。
- **S-2** 明确 `sessions.title`（首 12 字明文）的豁免或加密策略。
- **S-3** `miniprogram/components/crisis-card/crisis-card.js`：仅过滤 `X`，建议同时过滤 `0XX` 与无效号。
- **S-4** 清理根目录两份散落中文文档，遵守 `repo-governance.md` §3。
- **S-5** 合规过滤误伤转述句（“如果医生诊断你为抑郁症呢”），建议只替换结论子句而非整句。

## 5. 上线判定

**不可上线。** 需要至少完成：

1. 修复 B-1：把整改依赖模块全部入库，保证 `HEAD` 可 `import`、CI 全绿（这是硬前置，否则任何部署都会失败）。
2. 修复 B-2：补齐合规过滤的绕过面与切分漏检，否则不满足输出侧合规验收。
3. 修复或明确接受 H-1（流式截断/断连丢消息）与 H-2/H-3（危机误报与词库替换）的风险；H-4 需拿到校方书面确认。
4. 外部依赖：域名、证书、微信域名白名单、校心理中心对接仍需在真实环境完成实测。
