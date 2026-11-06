# 「心屿」代码审查报告（2026-11-06）

> **审查方式**：使用 `code-review-report-plugin` 的 `review-code-report` 技能 Phase A 方法（先固定快照 → 通读 diff → 候选问题取证 → 交叉核对 → 过滤误报），并按 `docs/repo-governance.md` 要求以纯 Markdown 落盘，未发布交互式卡片报告。
> **只读审查**：未修改任何业务代码、未改动 `.env`、未提交 Git。
> **补充验证**：`backend/.venv/bin/ruff check .` → `All checks passed!`；`find miniprogram -name '*.js' -exec node --check {} +` → 通过；未运行 `pytest`（需本地 MongoDB），相关结论均标注为静态审查。

---

## 一、审查范围与快照

| 项 | 内容 |
|---|---|
| 工作区未提交改动 | `git status` 显示 **52 个已跟踪文件修改 + 28 项未跟踪（含目录）**，共 80 项 |
| 小程序改动 | `app.wxss`、`styles/emotion.wxss`、`pages/{index,chat,logs,memories,mine,practice,sessions}`、`components/crisis-card`、`utils/api.js` |
| 后端改动 | `services/{chat,crisis,emotion,long_memory,privacy,alerting}.py`、`config.py`、`core/ratelimit.py`、新增 `core/{cost,counter,llm_json,metrics,redis_client,text}.py`、`llm/{qwen,fallback,router}.py`、`db/user_data_registry.py`、`nginx/` |
| 近期提交 | `a2670c2` 长期记忆抽取指令改为优先级序列 + 危机表达强制空数组 |
| 严重度口径 | 阻断上线 = 合规红线或必然导致不可用/数据泄露；高风险 = 特定条件下可造成实质伤害或明显体验塌陷；建议改进 = 可维护性、一致性、边界体验 |

---

## 二、结论摘要

**整体判断：当前不可上线。** 存在 3 个阻断项（敏感心理数据明文落库且数据库无认证、危机内容可进入长期记忆、生产链路仅 HTTP），另有 SSE 假流式、输出侧合规无兜底等高危项；小程序本轮 P0/P1 视觉改造本身未发现致命缺陷，仅有 1 处样式引用断裂和若干边界/对比度问题。

**最严重的 3 个问题**

1. **【阻断】敏感心理内容明文落库 + MongoDB 无认证且端口对外发布。** 对话正文已加密，但情绪分析摘录（`evidence`）、打卡备注（`note`）、模型兜底风险事件（`matched`）均为明文；`mongod --bind_ip_all` 且 `27017:27017` 发布到宿主机，生产配置校验也未拦截无认证连接串。与用户同意弹窗「对话内容采用加密存储」的承诺不一致。
2. **【阻断】mid 级危机内容仍会进入长期记忆抽取。** `_schedule_memory_extraction` 只跳过 `high`，而「活着没意思」「撑不下去」等单词命中即判为 `mid`；抽取指令中的「危机一律空数组」只是提示词约束，确定性代码层没有拦截，危机内容可能被长期留存并再次注入后续对话。
3. **【阻断】生产 Nginx 只监听 80，HTTPS 整段注释。** 若按当前配置上线，登录凭证、对话内容、数据导出均走明文 HTTP；且微信小程序要求 HTTPS 合法域名，提审与真机调用都无法通过。

---

## 三、阻断上线（P0）

### B1 敏感心理数据明文落库，叠加 MongoDB 无认证暴露

**证据**

- 对话正文加密后入库，但情绪摘录直接明文写入消息子文档与 `emotion_records`：
  [`backend/app/services/emotion.py#L213-L238`](../backend/app/services/emotion.py#L213-L238)

  ```python
  emotion = {"type": ..., "intensity": ..., "evidence": analysis.evidence, ...}
  await mongo.db[COLL_MESSAGES].update_one({"_id": assistant_message_id}, {"$set": {"emotion": emotion}})
  # 2) 写 emotion_records（仅记录结构化结果，不存对话原文）
  await mongo.db[COLL_EMOTION_RECORDS].insert_one({..., "evidence": analysis.evidence, ...})
  ```

  同一文件 [`L127`](../backend/app/services/emotion.py#L127) 明确要求 `"evidence": "不超过50字的原文摘录"`，即该字段就是用户原话。注释「不存对话原文」与实现不符。
- 打卡备注同样未加密：[`backend/app/services/checkins.py#L44-L53`](../backend/app/services/checkins.py#L44-L53)

  ```python
  "$set": {"mood": mood, "intensity": MOOD_INTENSITY[mood], "note": note},
  ```

- 模型兜底风险事件把模型摘录塞进 `matched`，与「仅命中词，不写对话原文」的注释冲突：
  [`backend/app/services/crisis.py#L105-L130`](../backend/app/services/crisis.py#L105-L130)、[`L133-L151`](../backend/app/services/crisis.py#L133-L151)

  ```python
  """写 risk_events（仅命中词，不写对话原文），留存 ≥12 个月供审计。"""
  ...
  "matched": matched,
  ...
  await record_risk_event(user_id, session_id, "high", matched=[evidence] if evidence else [], trigger="model")
  ```

- MongoDB 无认证且对外发布：[`backend/docker-compose.yml#L4-L12`](../backend/docker-compose.yml#L4-L12)

  ```yaml
  ports: ["27017:27017"]
  command: ["mongod", "--bind_ip_all"]
  ```

  连接串默认无凭据：[`backend/app/config.py#L20`](../backend/app/config.py#L20)；生产校验只检查 JWT/加密密钥/微信/智谱/ASR，未要求 Mongo 认证：[`backend/app/config.py#L149-L179`](../backend/app/config.py#L149-L179)。
- 前端同意文案「对话内容采用加密存储」：[`miniprogram/pages/index/index.js#L92-L94`](../miniprogram/pages/index/index.js#L92-L94)

**影响**：任何能访问 27017 的主体（同宿主机其他容器、误暴露公网、运维误操作）可一次性导出用户完整心理画像：对话 + 情绪摘录 + 打卡备注 + 危机事件。属敏感个人信息（PIPL 第 28 条），泄露后果远高于普通业务数据。

**触发条件**：生产按当前 compose 启动且未额外加防火墙/认证；或数据库备份、只读账号被滥用。

**修复方向**
1. 生产 compose 开启 `--auth` + `MONGO_INITDB_ROOT_USERNAME/PASSWORD`，连接串使用独立最小权限账号，且不要发布 `27017` 到宿主机（仅容器网络）。
2. 对 `emotion_records.evidence`、`checkins.note`、`risk_events.matched`（模型触发时）复用 `core.crypto.encrypt`；模型兜底的 `matched` 只存风险类别/哈希，不存原句。
3. 生产配置校验增加：`MONGODB_URI` 必须含凭据，否则拒绝启动。
4. 提供一次性迁移脚本，把历史明文 evidence/note 加密回填，并记录迁移批次。

**预估成本**：1.5–2 人日（含迁移与回归；不含 Mongo 认证联调环境）。

---

### B2 mid 级危机内容会进入长期记忆

**证据**

- 记忆抽取仅跳过 `high`：[`backend/app/services/chat.py#L187-L197`](../backend/app/services/chat.py#L187-L197)

  ```python
  if not get_settings().long_memory_enabled or turn.crisis.level == "high":
      return
  asyncio.create_task(long_memory.extract_and_save(...))
  ```

- 单个二级词命中即 `mid`（2 分，未达 4 分升级线）：[`backend/app/services/crisis.py#L87-L100`](../backend/app/services/crisis.py#L87-L100)；二级词包含「活着没意思」「撑不下去」「活着好累」等：[`backend/app/services/crisis_data.py#L37-L47`](../backend/app/services/crisis_data.py#L37-L47)
- 唯一防线是提示词：「涉及自伤、自杀等危机信息一律不要抽取……一律输出空数组」：[`backend/app/services/long_memory.py#L61-L90`](../backend/app/services/long_memory.py#L61-L90)
- 项目自己的边界声明是「涉及自伤/自杀等危机信息一律不抽取为记忆」：[`backend/app/services/long_memory.py#L13`](../backend/app/services/long_memory.py#L13)

**影响**：一条「活着没意思」经过回复后，后台会把相关事实抽取为长期记忆（加密存储但长期保留），并在后续会话按关键词重合注入，等于把危机内容长期留存、反复回到对话里。直接违反产品对用户的隐私承诺，也放大了二次伤害与合规风险。

**触发条件**：用户单轮命中任一二级词（`mid`），且轻量模型未严格按指令输出空数组（提示词不具确定性）。

**修复方向**
1. 在 `_schedule_memory_extraction` 中把门槛改为 `turn.crisis.level in ("mid", "high")` 直接返回，或在 `extract_and_save` 入口做同样的确定性判断（双保险）。
2. 抽取结果落库前增加后端确定性关键词复核：`normalize(content)` 命中任一 L1/L2 词即整批丢弃，不依赖模型自检。
3. 增加回归用例：mid 命中「活着没意思」时断言 `memories` 集合零写入。

**预估成本**：0.3–0.5 人日（含测试）。

---

### B3 生产仅 HTTP 80，HTTPS 未启用

**证据**

- 唯一启用的 server 块只有 `listen 80`：[`backend/nginx/nginx.conf#L53-L55`](../backend/nginx/nginx.conf#L53-L55)
- 443/TLS 整段仍是注释，且要求手工放证书后启用：[`backend/nginx/nginx.conf#L115-L128`](../backend/nginx/nginx.conf#L115-L128)

**影响**：登录 code、JWT、对话内容、数据导出全链路明文传输；微信小程序合法域名校验要求 HTTPS，真机与提审均无法通过。

**触发条件**：按 `prod` profile 直接部署。

**修复方向**：域名备案 + 证书就绪后启用 443 server（TLS1.2/1.3），80 端口 301 跳转；补充 HSTS；将反向代理 location 抽成 include 供 80/443 复用，避免两份配置漂移。

**预估成本**：0.5 人日配置 + 外部备案/证书周期（不可控）。

---

## 四、高风险（P1）

### H1 SSE 是「假流式」：全量生成完才一次性下发，且无心跳

**证据**

- 生成阶段先收齐所有 chunk，再逐个 yield：[`backend/app/services/chat.py#L222-L254`](../backend/app/services/chat.py#L222-L254)、[`L289-L303`](../backend/app/services/chat.py#L289-L303)

  ```python
  chunks, degraded = await _collect_stream(turn)
  for piece in chunks:
      yield "delta", {"content": piece}
  ```

- Nginx 虽已配置 `proxy_buffering off`、`proxy_read_timeout 75s`：[`backend/nginx/nginx.conf#L74-L83`](../backend/nginx/nginx.conf#L74-L83)，但上游在模型返回前没有任何字节可发。

**影响**：客户端 TTFB ≈ 整段生成耗时（主档通常数秒到十几秒），「正在输入」期间用户看到空白气泡；模型 30s 超时 + 失败重试一次可能接近 60s，再叠加情绪分析 5s，逼近 75s 读超时，弱网下易被网关/客户端打断。配置了流式但没有获得流式的体验收益。

**触发条件**：每次对话（非 high 危机路径）。

**修复方向**：把 `provider.stream` 的 delta 直接透传给 `event_generator`，落库/情绪分析放到流结束后；每 10–15s 发送 `: keep-alive` 注释帧；为流式生成加整体 deadline，避免 30s×2 叠加。

**预估成本**：1–1.5 人日（需回归 done/finish/降级/危机事件的顺序）。

---

### H2 合规边界只有提示词，没有输出侧后置校验

**证据**

- 系统提示词有「不做诊断、不推荐任何药物、不贴标签」：[`backend/app/services/prompts.py#L21-L28`](../backend/app/services/prompts.py#L21-L28)
- 全仓未发现对模型输出的合规过滤/替换函数（`grep` 无 `sanitize/filter/合规过滤` 实现，仅提示词命中）；`high` 路径固定话术不受影响，但 `none/mid` 路径的回复原样下发。

**影响**：模型漂移或用户诱导（「我是不是抑郁症」「吃什么药」）时，可能输出诊断性结论、药名或疗效承诺，直接触碰医疗广告与互联网诊疗红线；当前没有任何运行时兜底或告警。

**触发条件**：提示词失效、模型换版、对抗性提问。

**修复方向**：回复落库前增加规则层（诊断词/药名/疗效词表 + 否定语境白名单），命中则替换为安全话术并记录 `compliance_hit` 指标；同时把该规则纳入评估集回归。

**预估成本**：1 人日（规则 + 测试 + 评估集）。

---

### H3 校心理咨询中心电话仍是占位符，转介闭环不完整

**证据**：[`backend/app/services/crisis_data.py#L61-L74`](../backend/app/services/crisis_data.py#L61-L74)

```python
{"id": "campus-center", "name": "校心理咨询中心", "phone": "0XX-XXXXXXXX",
 "hours": "工作日 9:00–17:00", "note": "线下预约（电话待补充）", "priority": 4}
```

前端会把含 `X` 的号码判为不可拨打，只提示「该电话待补充」：[`miniprogram/components/crisis-card/crisis-card.js#L26-L31`](../miniprogram/components/crisis-card/crisis-card.js#L26-L31)。

**影响**：校园场景最核心的线下转介入口不可用，危机卡片只能依赖全国热线；与「校心理中心对接」的上线门控冲突。

**修复方向**：上线前由校方提供真实号码与值班时段；若短期无法提供，至少在卡片中给出明确的到访地点/预约路径，不让最后一条资源形同虚设。

**预估成本**：外部依赖；配置改动 < 0.1 人日。

---

### H4 危机词库加载会「整体替换」内置兜底，且累计分按会话隔离

**证据**

- DB 中只要有一条启用词，就会完全替换内置 L1/L2，而不是合并：[`backend/app/services/crisis.py#L43-L65`](../backend/app/services/crisis.py#L43-L65)

  ```python
  l1 = sorted(set(l1 or LEVEL1_PHRASES))
  l2 = sorted(set(l2 or LEVEL2_PHRASES))
  ```

- 二级分累计读取的是当前会话的 `crisis_score`：[`backend/app/services/crisis.py#L87-L100`](../backend/app/services/crisis.py#L87-L100)

  ```python
  current_score = session.get("crisis_score", 0) or 0
  ```

**影响**：① 运营若只录入少量词库（或误删），红线词覆盖会瞬间收缩到只剩那几条，且无告警；② 用户在 5 个会话间分散表达二级信号，每个会话都停留在 `mid`，永远不会升级到 `high` 固定话术。

**修复方向**：DB 词库与内置兜底取并集，删除词条走单独的禁用表；`high` 判定改为「近 N 天跨会话累计分」，或至少把 `crisis_score` 提升到用户维度。

**预估成本**：0.5–1 人日。

---

## 五、建议改进（P2）

### M1 `inline-card` 样式引用断裂（自定义组件样式隔离）

**证据**：页面给组件传了外部类 [`miniprogram/pages/chat/chat.wxml#L15-L24`](../miniprogram/pages/chat/chat.wxml#L15-L24)，样式定义在页面 [`miniprogram/pages/chat/chat.wxss#L16-L18`](../miniprogram/pages/chat/chat.wxss#L16-L18)，但组件未声明 `externalClasses`：[`miniprogram/components/crisis-card/crisis-card.js#L2-L8`](../miniprogram/components/crisis-card/crisis-card.js#L2-L8)。

**影响**：`margin: 8rpx 0 8rpx 88rpx` 不生效，mid 危机卡片与气泡左对齐、上下贴边，视觉层级与设计稿不一致。属于本轮 P0/P1 改造中唯一确认的「样式引用断裂」。

**修复方向**：`Component({ externalClasses: ['inline-card'], ... })`；或把外边距内聚到组件的 `--mid` 修饰类。

**成本**：0.2 小时。

### M2 情绪标签文字使用装饰色，对比度不足；且情绪色未纳入设计令牌

**证据**：`.tl-label` 直接消费 `--emo-ink` 作为文字色 [`miniprogram/pages/logs/logs.wxss#L192-L196`](../miniprogram/pages/logs/logs.wxss#L192-L196)；色值如 `#6fae7f`、`#e0913e`、`#e06666` 对白底对比度约 2.3–3.2:1（[`miniprogram/styles/emotion.wxss#L10-L55`](../miniprogram/styles/emotion.wxss#L10-L55)），低于正文 AA 4.5:1。文件头注释称「不新增任何 hex」，但这 9 个色值均不在 [`miniprogram/app.wxss#L11-L49`](../miniprogram/app.wxss#L11-L49) 的语义色板中。

**影响**：情绪文字（关键信息）在弱光/老年模式/低端屏上可读性差；后续换肤只能改这份「唯一来源」，全局主题令牌无法覆盖。

**修复方向**：文字色改用 `--text` / `--text-2`，颜色只留给色点；把情绪色提升为 `app.wxss` 的 `--emo-*` 令牌或在 emotion.wxss 中引用现有 `--success/--warn/--danger` 派生色。

**成本**：0.5 小时。

### M3 2000 字边界文案不一致

**证据**：[`miniprogram/pages/chat/chat.js#L10-L18`](../miniprogram/pages/chat/chat.js#L10-L18)

```js
const left = MAX_LEN - len
countText: left < 0 ? `超出 ${-left} 字` : `还能写 ${left} 字`
```

正好 2000 字时显示「还能写 0 字」，首页同类场景则显示「已写满 200 字」[`miniprogram/pages/index/index.wxml#L63`](../miniprogram/pages/index/index.wxml#L63)。1800/1801 的显示切换本身正确（`len <= 1800` 隐藏，1801 显示 199），无 off-by-one。

**修复方向**：`left === 0` 时显示「已写满」，与首页对齐。

**成本**：0.1 小时。

### M4 `crisis-card` 重复定义 `data`

**证据**：[`miniprogram/components/crisis-card/crisis-card.js#L8-L11`](../miniprogram/components/crisis-card/crisis-card.js#L8-L11) 与 [`L34-L38`](../miniprogram/components/crisis-card/crisis-card.js#L34-L38) 各有一个 `data` 对象，后者覆盖前者。

**影响**：当前字段并集刚好覆盖（`title/subtitle/_items`），暂无功能故障；但后续在第一个 `data` 里加字段会被静默丢弃，属于易踩坑的重复定义。

**修复方向**：合并为一个 `data`。

**成本**：0.1 小时。

### M5 语音上传不处理 401 刷新，`ensureLogin` 也不校验过期

**证据**：`ensureLogin` 只判断 token 是否存在 [`miniprogram/utils/api.js#L93-L96`](../miniprogram/utils/api.js#L93-L96)；`uploadFile` 直接携带当前 token，无 401 → refresh → 重放逻辑 [`miniprogram/utils/api.js#L145-L177`](../miniprogram/utils/api.js#L145-L177)。普通请求的并发刷新共享机制本身是正确的（`refreshPromise` 单飞，[`L98-L118`](../miniprogram/utils/api.js#L98-L118)）。

**影响**：access token 过期后首次操作若是录音转写，会直接提示「上传失败（401）」，需等其它请求触发刷新后重试；对语音入口是可见的挫败点。

**修复方向**：`uploadFile` 捕获 401 后调用与 `request` 相同的刷新/重登流程并重试一次。

**成本**：0.5 小时。

### M6 「今天」判定使用 UTC 日期，00:00–08:00 无法编辑当日备注

**证据**：[`miniprogram/pages/logs/logs.js#L115-L118`](../miniprogram/pages/logs/logs.js#L115-L118)

```js
const todayStr = new Date().toISOString().slice(0, 10)
const canEditNote = it.source === 'checkin' && (it.created_at || '').slice(0, 10) === todayStr
```

后端 `created_at` 是 `+08:00` 的 CST 日期（[`backend/app/core/timeutil.py#L16-L20`](../backend/app/core/timeutil.py#L16-L20)），而 `toISOString()` 取 UTC 日期。

**影响**：每天 00:00–07:59（CST），今日打卡的 `canEditNote` 为 false，时间线不出现「编辑今天的备注」；反而昨天 16:00 之后的记录可能被误判为今天。属条件判断边界错误。

**修复方向**：用本地日期拼接（`getFullYear/getMonth/getDate` 或后端返回的 `date` 字段）比较。

**成本**：0.3 小时。

### M7 数据导出接口无应用层限流

**证据**：导出接口只做登录校验，无 `rate_limit` 依赖 [`backend/app/api/routes/users.py#L60-L64`](../backend/app/api/routes/users.py#L60-L64)；单次返回全部对话（解密后）、情绪摘录、打卡备注与风险事件 [`backend/app/services/privacy.py#L95-L140`](../backend/app/services/privacy.py#L95-L140)。

**影响**：账号被盗后可高频拉取完整心理档案（Nginx 仅按 IP 60 次/分钟）；导出内容本身是用户行权所需，但应做频控与审计。

**修复方向**：加用户维度限流（如 1 次/分钟、5 次/天）+ 导出审计日志（只记条数与 IP，不记内容）。

**成本**：0.5 小时。

### M8 仓库根目录混入本地文档（治理规范）

**证据**：未跟踪项包含根目录 `创新实践周-开题报告（可复制版）.md`、`学号-姓名-创新实践周-报告.md`，与 `docs/repo-governance.md` 的「本地文档不得散落在根目录」「根目录只含项目级文件」冲突（[`docs/repo-governance.md#L53`](./repo-governance.md#L53)、[`#L60`](./repo-governance.md#L60)）。同时 `tools/gen_icons.py`、`.brooks-lint-history.json` 也是未登记的新增项。

**影响**：提交时容易误入库，破坏根目录清洁与提交审查。

**修复方向**：移出仓库或纳入 `.gitignore`；`tools/` 若保留请在 README/治理文档登记用途。

**成本**：0.1 小时。

---

## 六、小程序 P0/P1 改动专项核查（重点范围）

| 核查项 | 结论 | 证据 |
|---|---|---|
| WXML class 与 WXSS 定义匹配 | 除下列 1 项外全部匹配；`trend-title` 无样式定义但不影响布局（仅包裹用） | 脚本全量扫描 `pages/*/*.wxml` 对比页面样式与 `app.wxss` |
| 动态拼接 `emo--{{...}}` | **当前可达取值全部有定义**：打卡 `calm/ok/low/anxious/irritable`，日志 `calm/ok/depressed/anxious/angry/other`；`logs.js` 对未知情绪兜底 `other` | [`styles/emotion.wxss#L10-L56`](../miniprogram/styles/emotion.wxss#L10-L56)、[`logs.js#L5-L22`](../miniprogram/pages/logs/logs.js#L5-L22)、[`index.js#L5-L11`](../miniprogram/pages/index/index.js#L5-L11) |
| 自定义组件内样式变量 | `crisis-card` 全部使用字面值，未依赖页面令牌，无失效；风险仅在后续有人在组件内使用 `--emo-*`（页面样式隔离） | [`components/crisis-card/crisis-card.wxss`](../miniprogram/components/crisis-card/crisis-card.wxss) |
| `styles/emotion.wxss` 被两页 `@import` | **无重复定义问题**：WXSS 按页面作用域生效，`index.wxss`/`logs.wxss` 自身均未重复定义 `.emo--*`，不存在后者覆盖前者 | [`index.wxss#L1`](../miniprogram/pages/index/index.wxss#L1)、[`logs.wxss#L1`](../miniprogram/pages/logs/logs.wxss#L1) |
| `tl-badge` 结构与新样式 | 匹配：徽章承载 `--emo-bg` 背景，内部 28rpx 色点自绘；72rpx 容器 + 28rpx 色点比例正常 | [`logs.wxml#L49-L56`](../miniprogram/pages/logs/logs.wxml#L49-L56)、[`logs.wxss#L170-L180`](../miniprogram/pages/logs/logs.wxss#L170-L180) |
| 删 wxml 留死样式 / 反之 | 已清理：`empty-emoji`、`mood-emoji`、`done-emoji` 均无残留引用与定义；新增 `empty-action` 有定义有用例 | 全仓 `grep` |
| 条件渲染状态残留 | 未发现：`highCard` 随页面实例销毁；mid 卡片按 `key` 定向删除；发送时同步复位 `inputValue/canSend/over/countText` | [`chat.js#L290-L304`](../miniprogram/pages/chat/chat.js#L290-L304) |
| 字数阈值 1800/2000 | 1800/1801 切换正确；仅 2000 整点文案为「还能写 0 字」（M3） | [`chat.js#L10-L18`](../miniprogram/pages/chat/chat.js#L10-L18) |
| 页面跳转 | 对话页为 tab，`sessions/index/logs/memories` 全部用 `wx.reLaunch` 携带 `session_id`，不存在 `navigateTo` 打开 tab 页的失败 | 全仓 `grep pages/chat/chat` |
| token 刷新并发 | `refreshPromise` 单飞 + `loginPromise` 单飞，冷启动并发 401 只刷新/登录一次；缺口在 `uploadFile`（M5） | [`api.js#L67-L143`](../miniprogram/utils/api.js#L67-L143) |
| 全局 WXSS 变量完整性 | 除 `.emo--*` 自定义属性（由情绪类自带）外，所有 `var(--x)` 均在 `app.wxss` 有定义 | 脚本校验 |

**补充**：`.emo-glyph` 的背景/描边未写 fallback（[`emotion.wxss#L59-L72`](../miniprogram/styles/emotion.wxss#L59-L72)）。现有取值都安全，但若后端未来新增情绪枚举而前端未同步，色点会退化为不可见。建议给 `var(--emo-bg, #f3f0eb)`、`var(--emo-ink, var(--text-3))` 兜底。

---

## 七、合规红线复核

| 红线 | 结论 | 依据 |
|---|---|---|
| 是否可能输出诊断结论 | **可能**。提示词明确禁止，但无输出侧校验/兜底 | [`prompts.py#L24-L28`](../backend/app/services/prompts.py#L24-L28)；全仓无后置过滤实现 |
| 是否可能推荐药物 | **可能**，同上；无药名规则层 | 同上 |
| 是否宣称疗效 | **可能**，同上；策略层只控制语气，不限制疗效表述 | [`prompts.py#L36-L52`](../backend/app/services/prompts.py#L36-L52) |
| 危机词库能否被绕过 | **能**，有三条路径：① 繁体/拼音/英文表达不在简体词库（归一化只做小写与去标点，[`core/text.py#L10-L15`](../backend/app/core/text.py#L10-L15)）；② 二级分按会话隔离，跨会话分散表达不升级；③ DB 词库一旦有数据即整体替换内置兜底 | [`crisis.py#L43-L65`](../backend/app/services/crisis.py#L43-L65)、[`L87-L100`](../backend/app/services/crisis.py#L87-L100) |
| 危机转介链路是否完整 | **不完整**：校心理中心电话为 `0XX-XXXXXXXX`，前端判定不可拨打 | [`crisis_data.py#L72`](../backend/app/services/crisis_data.py#L72) |
| 日志是否泄露心理数据 | **未发现**：对话/记忆/转写日志只记录长度、条数、session 标识；`ruff`/`grep` 未见原文进日志 | [`speech.py#L94`](../backend/app/services/speech.py#L94)、[`long_memory.py#L222-L223`](../backend/app/services/long_memory.py#L222-L223) |
| 数据导出是否泄露可识别心理数据 | **导出内容本身是用户行权所需（本人鉴权）**，但：① 无应用层限流；② 生产 HTTP 明文传输（B3）；③ 导出含明文摘录 `evidence`/`note`/`matched` | [`users.py#L60-L64`](../backend/app/api/routes/users.py#L60-L64)、[`privacy.py#L110-L140`](../backend/app/services/privacy.py#L110-L140) |
| 敏感数据静态存储 | **不合规**：见 B1，明文摘录 + 无认证数据库 | 见 B1 |

**总结**：合规风险集中在「提示词软约束 + 明文留存 + 传输明文」三处，均不是模型能力问题，而是工程门控缺失；B1/B2/B3 修复后可把红线风险降到可接受区间，H2/H3 仍需在上线前闭环。

---

## 八、建议修复顺序

| 顺序 | 事项 | 目标 | 预估 |
|---|---|---|---|
| 1 | B1 Mongo 认证 + evidence/note/matched 加密（含历史迁移） | 消除批量泄露与承诺不一致 | 1.5–2 人日 |
| 2 | B2 mid 危机不进记忆 + 落库前确定性复核 | 兑现「危机不长期留存」 | 0.3–0.5 人日 |
| 3 | B3 启用 HTTPS + 域名/证书 + 80→443 | 满足微信提审与传输合规 | 0.5 人日 + 外部周期 |
| 4 | H3 校心理中心真实号码/到访路径 | 转介闭环可用 | 外部依赖 |
| 5 | H2 输出侧合规规则层 + 评估集回归 | 防诊断/药物/疗效输出 | 1 人日 |
| 6 | H1 SSE 透传 + 心跳 + 整体 deadline | 恢复流式体验、降低超时中断 | 1–1.5 人日 |
| 7 | H4 词库并集、跨会话累计分 | 降低危机漏判 | 0.5–1 人日 |
| 8 | M1–M8 前端与治理项 | 视觉一致性、边界体验、仓库卫生 | 合计约 1 人日 |

---

## 九、验证记录与限制

- `backend/.venv/bin/ruff check .`：**All checks passed**。
- `find miniprogram -name '*.js' -exec node --check {} +`：**全部通过**（无语法错误）。
- 未运行 `pytest`：本机未确认 MongoDB 测试实例，避免把环境失败误判为代码缺陷；后端结论均来自静态证据与调用链阅读。
- 未做真机/开发者工具渲染验证：`.inline-card` 失效依据微信自定义组件默认 `isolated` 样式隔离规则判定，建议修复后在开发者工具复核一次。
- 未审查 `docs/` 下既有报告的结论，本报告独立取证；与旧报告如有冲突，以本报告行号证据为准。
