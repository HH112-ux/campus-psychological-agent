# 上线就绪度全量审查报告（第 10 轮）

> 审查日期：2026-11-11
> 审查对象：`main` HEAD `8f87bfa`（`docs(deploy): add prod compose drill report (#1)`）
> 审查性质：全量上线就绪度评估（非定向复核）
> 审查方式：只读。未修改业务代码、未提交、未推送、未改动 `.env`
> 证据标准：`trae-remote-official:code-review-report-plugin:review-code-report`（源码取证 + 可复现命令 + 分级去重）

> **整改情况补记（2026-11-11）**：本报告基于 `8f87bfa` 取证。在其后的 `8f87bfa..eda4ac6` 共 16 个提交中，**8 项阻断已全部修复**（B-1 `46ec539`、B-2 `07df597`、B-3 `16f674a`、B-4 `debfee1`、B-5 `b0524b0`、B-6 `b0a1f99`、B-7 `38ea272`、B-8 `8c632c0`）。本轮整改另修复了 P-1（purge 调度慢启动永不启动）、P-2（长期记忆解密异常 500）、P-7（nginx 等待 api 健康）、P-9（治理文档 node --check 命令）、P-13（会话重命名/删除失败分支）、P-15（非法 sub 归一 401）、P-16（主模型空响应切备）。当前 `HEAD eda4ac6` 实测 `ruff` 全过、`1128 passed / 1 skipped`、小程序 12 个 JS `node --check` 全过、文档事实校验通过。剩余 P-3/P-4/P-5/P-6/P-8/P-12/P-14 转入上线后迭代。

---

## 一、结论

**当前代码未达到上线标准。**

质量门本身是干净的（干净快照 `ruff` 全过、`1009 passed / 1 skipped`、小程序 11 个 JS 全过），前九轮已闭环的机制也仍然闭环；但本轮的全量取证发现了 **8 项必须在上线前清掉的阻断项**，集中在危机词库召回、生产配置默认值、隐私同意强制、会话标题明文、代理后登录限流、危机链路与 DB 耦合、输出侧合规规则、小程序发布地址。

按修复成本从低到高排序的必清清单见第九节。其中前四项（发布地址、`ENV=prod` 强制、代理头真实 IP、危机链路兜底）都是**分钟到小时级**的改动，不具备"上线后再补"的合理性。

另需说明：工作区当前存在未提交的 `README.md`、`CHANGELOG.md`、`docs/improvement-roadmap.md` 改动及若干未跟踪文档。本报告所有证据以 **HEAD `8f87bfa`** 为准，未把工作区改动计入。

---

## 二、质量门（干净快照）

### 2.1 快照与依赖

```bash
git archive HEAD | tar -x -C /tmp/recheck10
python3.12 -m venv /tmp/recheck10/backend/.venv
uv pip install --python /tmp/recheck10/backend/.venv/bin/python \
  --index-url https://mirrors.aliyun.com/pypi/simple \
  -r /tmp/recheck10/backend/requirements-dev.txt
```

依赖安装成功（首次直连 PyPI 与清华镜像均超时，改用阿里云镜像完成；属环境问题，不构成项目缺陷）。

### 2.2 后端质量门

```bash
cd /tmp/recheck10/backend
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
```

实际输出：

```
All checks passed!

SKIPPED [1] tests/test_ratelimit_redis.py:170: 未设置 REDIS_TEST_URL，跳过真 Redis 集成测试
1009 passed, 1 skipped, 1 warning in 3.36s
```

收集数为 **1010** 项（1009 通过 + 1 条真 Redis 集成用例按 `REDIS_TEST_URL` 跳过）。CI 中该用例会真实执行（`ci.yml:60-61` 配了 `REDIS_TEST_URL`）。

### 2.3 小程序质量门

```bash
cd miniprogram
find . -name '*.js' -not -path './node_modules/*' | while read f; do node --check "$f"; done
```

- 11 个 JS 文件全部通过，无 `FAIL` 输出。
- `app.json`：7 个页面，逐页校验 `.js/.json/.wxml/.wxss` 四个文件，缺失列表为空。
- TabBar 4 项、`iconPath`/`selectedIconPath` 共 8 个图标，全部存在。
- `sitemap.json` 存在。

### 2.4 覆盖范围

| 范围 | 结论 |
|---|---|
| `backend/app` 各层（api/core/services/llm/db/models） | 已读关键链路 |
| `backend/scripts`（init/seed/迁移/评估/压测） | 已抽查 |
| `backend/Dockerfile`、`docker-compose.yml`、`nginx/` | 已逐行核对 |
| `.github/workflows/ci.yml` | 已核对三个 job |
| `miniprogram/` 页面、组件、样式、`app.json` | 已核对语法、注册、资产、关键交互 |
| `docs/` 与仓库治理（README/CHANGELOG/治理规范） | 已核对口径一致性 |

### 2.5 本次未覆盖（结论边界）

- 未使用真实微信/智谱/ASR 凭据，未做真实第三方联调与真机验收。
- 未做容量压测与多实例部署验证。
- 危机词库召回率无法仅凭 152 条语料证明"≥95%"；语料未覆盖的表达（见 B-1）恰恰是漏报来源。
- 未做临床/心理专业复核，合规规则的语义边界需专业人员确认。

---

## 三、回归基线（前九轮已闭环项仍然成立）

在干净快照上重跑冻结语料，逐条比对，0 条不符：

| 语料 | 条目数 | 不符合 |
|---|---|---|
| `CRISIS_CASES` | 152 | 0 |
| `MEMORY_CASES` | 55 | 0 |
| `COMPLIANCE_CASES` | 137 | 0 |

前几轮修复的定点复验同样全部保持：

| 项 | 样本 | 结果 |
|---|---|---|
| 第 7 轮 15 条 `none→high` 副作用 | 15 | 15/15 仍为 high |
| 标点/换行硬边界 | 6 | 6/6 |
| 第 6 轮 8 条自然表达误报 | 8 | 8/8 仍为 none |
| 第 7 轮 9 条核心危机样本 | 9 | 9/9 结论不变 |
| `7c128e1`「不想活受罪」 | 1 | high（歧义按危险一侧） |
| 第 9 轮词库缓存 `None` 状态位 | 冷启动/refresh/TTL | 仍正确 |

结论：**既有回归基线没有退化**；本轮阻断项来自语料未覆盖的新表达与新发现的配置/链路问题，不是旧修复回退。

---

## 四、阻断上线（必须修）

### B-1 危机词库漏掉多种常见高危表达（危机链路，最高优先级）

**证据**（干净快照实测，内置词库）：

```
'我不活了'       -> none
'我今晚就去死'     -> none
'我要自尽'       -> none
'我想一死了之'     -> none
'我想离开人世'     -> none
'我不想再活了'     -> none
'我要去死'       -> none
'我活不下去了'     -> high      （对照：库内已有表达可命中）
'我想死'         -> high
```

词库现状：`crisis_data.py:19` 起 L1 共 102 条、L2 共 42 条；L1 含「想死/想自杀/不想活/活不下去/轻生」等，但**不含**「自尽」「去死」「一死了之」「离开人世」「不想再活」；「我不活了」也无法被「不想活了」子串覆盖。

**影响**：

1. 用户第一次说出上述表达时，不会出高危卡片、不给求助热线、不写 `risk_events`、不告警。
2. 由于 `contains_crisis_terms` 与 `detect_risk` 同口径（`crisis.py:358-362`），这些表达不会命中长期记忆兜底（`long_memory.py:192`、`:216`），危机内容可能被抽取为长期记忆并在后续对话中重新注入。
3. 模型侧兜底（`emotion.py:245-248`）是**回复完成后**的异步补救，只写事件并把 `crisis_high_shown` 置位，**当轮不给热线**，无法替代首轮拦截。

**修法**：补齐上述表达及其变体（含「不想再活」「不想活下去了」「去死」「自尽」「寻短见」等），同步补 `CRISIS_CASES`，并做一次临床/心理专业复核。成本：低（补词 + 用例），但必须做漏报/误报复核。

### B-2 生产编排未强制 `ENV=prod`，可静默以 dev 模式上线

**证据**：

- `backend/docker-compose.yml` 的 `api` 仅 `env_file: .env`，未设置 `ENV: prod`。
- `backend/.env.example:8` 为 `ENV=dev`，`:42` 为 `WX_MOCK_LOGIN=true`。
- `backend/app/config.py:160` 的生产强校验**只在 `env == "prod"` 时生效**。
- `backend/app/services/wechat.py:28-31`：mock 登录直接返回固定 `WX_MOCK_OPENID`。

**影响**：运维照 `.env.example` 复制并执行 `docker compose --profile prod up -d` 时，服务会以 dev 模式启动：mock 登录开启、生产校验全部跳过。此时**所有用户登录为同一个固定 openid（同一账号）**，聊天记录、长期记忆、打卡数据互相串号；同时弱 JWT、缺加密密钥等危险配置也不会被拦截。

**修法**：在 compose 的 `api.environment` 显式写 `ENV: prod`（或拆 `env_file.prod` 模板），`.env.example` 默认改为 prod 并注释 mock；`Settings` 对 mock 登录增加"非 dev 即拒绝"的方向性校验。成本：极低（分钟级）。

### B-3 隐私同意只在客户端提示，服务端未强制

**证据**：

- `backend/app/core/deps.py:14-24`：`get_current_user` 只校验令牌与用户存在，**未检查 `consent_at`**。
- `backend/app/services/chat.py:87-117`：`_pre_turn` 只做长度、内容安全、限流、轮次，**未检查同意状态**。
- `miniprogram/pages/index/index.js:75-76`：`maybeShowConsent()` 与 `loadHome()` 并行调用，弹窗未阻塞首页加载。
- `index.js:87-88`：`xinyu_consent_prompted` 在用户回答**之前**写入本地存储；用户取消（`:99-101`）只 toast，不会阻止后续使用；强杀小程序后不再弹窗。
- `backend/app/services/privacy.py:3` 自述"未同意时小程序必须先弹窗"——这只是前端约定，不是服务端约束。

**影响**：违反《个人信息保护法》对敏感个人信息"单独同意"的要求；任何绕过小程序的直接 API 调用都可在未同意状态下写入对话、情绪、打卡数据；用户拒绝后仍可继续产生数据。

**修法**：新增"业务路由必须已同意"的依赖（`/auth/*`、`/health`、`/crisis/resources` 除外），未同意返回明确业务码；前端在同意前不进入对话/打卡页；`consent_prompted` 改为同意成功后再写入。成本：中（后端依赖 + 前端路由门 + 测试）。

### B-4 会话标题明文落库、明文返回、明文导出

**证据**：

- `backend/app/services/chat.py:134-135`：首条消息 `session_set["title"] = text[:12]`，直接 `$set` 到 `sessions`。
- `backend/app/services/sessions.py:23`、`:97`、`:127`：列表、详情、重命名均直接读写明文 `title`。
- `backend/app/services/privacy.py:90`：数据导出直接返回明文 `title`。
- `README.md:62` 承诺"对话内容加密存储"，同意弹窗文案也向用户承诺"对话内容采用加密存储"（`index.js:93`）。

**影响**：用户首句常常就是最敏感的自我暴露（如"我不想活了，因为……"）。标题把前 12 个字明文写入数据库，使"对话内容加密"的承诺在数据层不成立；数据库备份、迁移、运维导出都会泄露这段原文。

**修法**：标题复用 `encrypt_optional_text` 加密、读取/导出时解密；或不再存储派生文本（由客户端本地生成标题）。历史数据需迁移脚本。成本：低到中（改动集中，含迁移与回归测试）。

### B-5 反向代理后登录限流键失效，退化为全站共享 10 次/分钟

**证据**：

- `backend/app/api/routes/auth.py:28-29`、`:47-48`：`ip = request.client.host`，再 `hit_login_rate(ip)`。
- `backend/app/core/ratelimit.py:124-125`：键为 `login:{ip}`，窗口 60 秒、上限 10。
- `backend/Dockerfile:24`：启动命令未带 `--proxy-headers` / `--forwarded-allow-ips`。
- uvicorn 默认 `proxy_headers=True`、`forwarded_allow_ips=127.0.0.1,::1`（快照 venv 实测）。
- `backend/nginx/nginx.conf.template:137-138` 会带 `X-Real-IP` / `X-Forwarded-For`，但 nginx 是独立容器，源地址不在受信列表，uvicorn 不采信。

**影响**：`request.client.host` 恒为 nginx 容器 IP，所有用户的登录/刷新共用 `login:<nginx-ip>` 一个键。全校只要 1 分钟内登录超过 10 次，第 11 个用户起全部 429；刷新令牌同样受限。这不是"防爆破"，而是把登录做成了全局限流。

**修法**：容器启动加 `--proxy-headers --forwarded-allow-ips=<nginx 网段>`（或设置 `FORWARDED_ALLOW_IPS`），仅信任来自 nginx 的转发头；`api` 当前只 `expose` 不发布端口，直连伪造风险可控。同时复核 nginx 层"10r/m/IP"在校园 NAT 下是否过严。成本：极低（分钟级）。

### B-6 高危危机响应与数据库强耦合，DB 异常即丢失热线与话术

**证据**：

- `backend/app/services/crisis.py:467`：命中后先 `await get_resources()`；`:507` 的 `find_one` **无 try**，docstring `:504` 却承诺"失败用内置兜底副本"。
- `crisis.py:472`、`:487`：`record_risk_event` 内 `insert_one` **无 try**（`:405`），异常直接向上抛。
- `backend/app/api/routes/messages.py:80`：`prepare_turn` 在 try 之外，异常直接返回 500 JSON。
- 兜底常量 `FALLBACK_RESOURCES` 存在（version 2，4 条资源），但只在 `db is None` 或文档为空时使用。

**影响**：用户说出高危语句的同一时刻，只要 Mongo 抖动、连接池耗尽或写 `risk_events` 失败，整个请求 500：**没有求助卡片、没有热线、没有告警**，用户只看到"服务异常"。这是危机链路最不该出现的失败模式。

**修法**：`get_resources` 的 DB 读取包 try 并回退 `FALLBACK_RESOURCES`；`record_risk_event` 写失败只记日志、不阻断；确保 `handle_detection` 永不抛。成本：低（半小时级）。

### B-7 输出侧合规规则漏拦诊断与疗效承诺

**证据**（干净快照实测）：

```
'你这叫抑郁症'        -> None      （漏）
'你这种状态叫焦虑障碍'   -> None      （漏）
'你是双相'          -> None      （漏）
'你可能有双相'        -> None      （漏）
'你能治好我的抑郁'      -> None      （漏）
'吃点药就好了'        -> None      （漏）
'这个药能治好你'       -> None      （漏）
'吃了这个药就会好'      -> None      （漏）
对照：
'你就是抑郁症'        -> diagnosis
'坚持两周一定能治好。'   -> efficacy
```

规则根因：

- `compliance.py:57-60` 的 `_DIAG_VERB_RE` 不含「叫 / 称作 / 算作」类判断词。
- `compliance.py:45-50` 的 `_DISORDERS` 只有「双相情感障碍 / 双相障碍」，裸「双相」不在表内。
- `compliance.py:121-131` 的疗效规则要求"保证/一定/肯定"或"治疗语境 + 结果词"，无法覆盖「能治好我的抑郁」「吃点药就好了」「这个药能治好你」。

**影响**：模型可以直接输出诊断结论或疗效承诺而不被替换，触碰"不提供诊断、不承诺疗效"的红线，属于提审与合规风险。

**修法**：补判断动词与裸病名（需带人称/语境约束，避免科普误伤）、补疗效句式；每条新规则必须同步补正反语料并跑全量误报回归。成本：中（规则 + 语料 + 误报仇审）。

### B-8 小程序发布地址仍指向本机回环

**证据**：

- `miniprogram/app.js:7`：`apiBase: 'http://127.0.0.1:8000'`。
- `miniprogram/project.config.json:8`：`urlCheck: false`。

**影响**：当前构建只能连开发者本机，无法连接线上 HTTPS 服务；`urlCheck: false` 会掩盖域名/证书配置错误。这是发布硬门，不是"上线后优化"。

**修法**：按环境注入 `apiBase`（正式域名必须 HTTPS 且已备案/配置合法域名），发布前开启 `urlCheck`。成本：分钟级。

---

## 五、上线前应做（不修也能跑，但会留下可见缺陷或隐患）

| # | 问题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P-1 | 物理删除调度只在"启动时 DB 已连通"才创建 | `main.py:43-47` | Mongo 启动慢于 API 时，`run_purge_scheduler` 永不启动，"软删 N 天后物理删除"的合规承诺不兑现，且无重试 | 启动后再探测/周期重试创建；或在调度器内部等待连接 |
| P-2 | 长期记忆解密在 try 之外 | `long_memory.py:329`、`:337` | 换密钥或脏数据会让 `decrypt` 抛错，违反"任何异常返回空，绝不阻断对话" | 把解密与排序整体包进 try，单条失败跳过 |
| P-3 | CI 评估门无 secret 时 SKIP 且 exit 0 | `ci.yml:92-98`、`:104-107` | CI 全绿不等于情绪/记忆评估达标；对外"CI 通过"易被误读 | 在 README/验收口径中显式标注 SKIP；有 secret 的分支必须留档 |
| P-4 | 多实例共享状态未落地 | compose 无 redis 服务；`main.py:39-41` 仅告警 | 一旦扩到 2 个 API 实例，限流、告警冷却、失败率计数全部失效 | 上线即用单实例；扩容前补 redis 服务与 `SHARED_STATE_BACKEND=redis` |
| P-5 | 第三方转述被当作本人危机 | 实测「室友说他想死」「我朋友说他想死」「新闻里有人想死」均判 high | 值班人收到噪信，且对被转述对象无实际帮助；告警含用户/会话 ID | 增加人称/转述主体判断，或把此类降为 mid 并提示"建议陪同求助" |
| P-6 | 80 端口明文暴露 `/health` | `nginx.conf.template:57-65` | `/health` 返回 `env`/`db` 状态，明文端口可被探测 | 仅保留 443 探活，或让 80 的 `/health` 只返回 200 不含细节 |
| P-7 | nginx 启动不等待 api 健康 | `docker-compose.yml` `depends_on: - api` | 冷启动瞬间可能出现 502 | 改用 `condition: service_healthy`（Dockerfile 已有 HEALTHCHECK） |
| P-8 | 镜像与构建不可复现 | `Dockerfile` 基础镜像未钉 digest；CI 不构建镜像、不跑 `compose config` | 演练报告已记录"必须手工打 tag / 临时改 pip 源" | 钉 digest、固化 pip 源、CI 增加镜像构建与编排校验 |
| P-9 | 治理文档的本地 JS 检查命令有误 | `docs/repo-governance.md:108` `find ... -exec node --check {} +` | `node --check` 只处理第一个文件，本地门形同虚设 | 改为 `-exec node --check {} \;` 或 `xargs -n1` |
| P-10 | 文档测试口径三处不一致 | HEAD `README.md:54` 写 153；工作区改为 220；`backend/README.md:121` 与 `CHANGELOG.md:24` 写 189；实际 1010 | 验收/答辩口径失真 | 统一改为"1010 收集、1009 通过、1 skip"并说明 skip 条件 |
| P-11 | README 技术栈含未使用依赖 | `README.md:34` 写 "LangChain"，`requirements.txt` 无该依赖 | 评审与面试口径失真 | 删除 LangChain 或补真实接入说明 |
| P-12 | 小程序发送失败清空输入且无重试 | `chat.js:295` 先清空，`:386-389` 仅 toast | 用户长文丢失，弱网下体验差 | 失败时回填输入并给"重试"入口 |
| P-13 | 会话重命名/删除无失败分支 | `sessions.js:80`、`:97` 无 `.catch` | 失败时无提示，列表与后端不一致 | 补 catch 与 toast |
| P-14 | 无障碍与对比度不足 | `app.wxss:30` `--text-3 #7a736b` 在 `#F7F4EF` 上约 4.26:1；`crisis-card.wxss:41-42` 关闭按钮 48rpx（约 24px） | 低于 4.5:1 与 44px 触达建议；危机卡片关闭按钮偏小 | 提高对比度、放大点击热区 |
| P-15 | 合法令牌 + 非法 `sub` 返回 404 | `deps.py` 走 `parse_oid` 抛 `CODE_NOT_FOUND`（演练坑 7） | 错误码语义不符，客户端按 401 重登录的逻辑失效 | 在 `get_current_user` 内把非法 id 归一为 401 |
| P-16 | 主模型返回空串/空流不切备用 | `fallback.py` 空结果直接返回 | 备用供应商形同虚设，用户得到空回复 | 空产出视为失败并切备 |

---

## 六、上线后迭代

| # | 事项 | 说明 |
|---|---|---|
| I-1 | 词库缓存 single-flight / 跨进程失效 | 第 9 轮已确认 `None` 状态位正确；并发首批仍会重复查 DB，`refresh` 只影响当前进程 |
| I-2 | 危机词库临床复核与误报率持续校准 | 语料只能证明"已知样本不退化"，不能证明真实召回；需心理专业老师参与 |
| I-3 | 多实例化（Redis 限流/冷却/计数） | 与 P-4 配套，扩容前完成 |
| I-4 | 备份、日志采集、外部探活告警 | Mongo 卷备份策略、日志落盘、`/health` 外部监控 |
| I-5 | 历史数据迁移编排 | 标题加密迁移、加密字段迁移的执行顺序与回滚点 |
| I-6 | 正式证书、域名、备案与真实凭据联调 | 微信/智谱/ASR 三条外部依赖尚未用真实凭据验证 |
| I-7 | 无障碍完整走查与空/错状态补齐 | 练习页 loading/empty、全局错误态 |
| I-8 | CI 硬化 | 镜像构建、`compose config`、依赖 hash、评估门 SKIP 显式化 |
| I-9 | 安全响应头补强 | HSTS `includeSubDomains`、按需 CSP（当前无 Web 前端，优先级低） |

---

## 七、专项结论

### 7.1 安全与隐私

**结论：不达标，1 项阻断（B-4），另有 B-2、B-3 两项阻断。**

- 通过：消息、打卡备注、情绪证据、风险命中词、长期记忆均走 `encrypt`/`encrypt_optional_text`；日志不含原文（告警只含 ID/级别/触发源，`alerting.py:63-74`）；鉴权覆盖全部业务路由，公开面仅 `/health`、`/crisis/resources`、`/auth/*`；Mongo 不发布宿主端口且强制 `--auth`；生产强校验覆盖 9 类危险配置（mock 登录、缺 AppID/Secret、关闭内容安全、弱 JWT、缺加密密钥、无认证 Mongo、缺模型 Key、非法求助电话、mock ASR）。
- 不通过：会话标题明文（B-4）；`ENV=prod` 未强制导致上述校验可整体绕过（B-2）；同意状态服务端不校验（B-3）。
- 密钥管理：`DATA_ENCRYPTION_KEY` 与数据库分离托管的设计正确；换密钥会导致历史数据不可解，需在运维手册中固化为"不可轮换或必须带迁移"。

### 7.2 危机链路

**结论：不达标，2 项阻断（B-1、B-6）。**

- 通过：high 先于任何 delta 且不调模型（`chat.py:325-332`）；mid 卡片在增量与落库之后、done 之前（`:369-370`）；风险事件留痕含级别/触发源/命中词（加密）；告警冷却跨实例（Redis 模式）且发送失败不占冷却；长期记忆写入前有确定性过滤。
- 不通过：常见高危表达漏报（B-1），并连带长期记忆过滤失效；危机响应与 DB 强耦合（B-6）。
- 设计提示：模型兜底是"下一轮才展示卡片"的异步补救，不能作为首轮拦截手段；第三方转述会造成告警噪信（P-5）。

### 7.3 合规输出

**结论：部分不达标，1 项阻断（B-7）。**

- 通过：非流式与流式共用同一套 `detect/sanitize/OutputGuard`；流式保留窗按归一化长度计算，逐字喂入仍能命中；多行只替换命中句、保留换行；繁体病名/药名有覆盖测试；停药/减量建议单独拦截。
- 不通过：「叫/称作 + 病名」「裸双相」「能治好我的抑郁」「吃点药就好了」等实际可绕过（B-7）。
- 说明：不能因为存在漏拦就把所有含病名的句子都拦掉——科普与第三方叙述必须放行，补规则时要同步跑误报回归。

### 7.4 稳定性

**结论：基本达标，存在可见隐患（P-1、P-2、P-4、P-16）。**

- 通过：SSE 5 秒心跳、`text/event-stream` 不压缩、`X-Accel-Buffering: no`；断连后生产者继续生成并落库（`chat.py:396-404`）；已产出部分失败标 `truncated`；主备切换与重试上限在 provider 契约层（base=2、fallback=1），双失败保留备用异常链；Redis 限流 fail-open。
- 隐患：物理删除调度可能永不启动；长期记忆解密异常会 500；多实例共享状态未落地；空响应不切备。

### 7.5 部署

**结论：编排可运行，但默认配置不安全（B-2、B-5、B-8 相关），并有若干硬化项。**

- 通过：prod 编排已在本机真实跑通（`docs/prod-deploy-drill-2026-11-10.md`）；TLS 唯一入口、80 跳转、白名单 404、安全响应头、Mongo 不对外、非 root（uid 10001）、healthcheck、加密字段迁移均实测通过；证书缺失时 nginx 启动即失败，不降级明文。
- 不通过/隐患：`ENV=prod` 未强制；代理头未配置导致限流键失效；基础镜像未钉 digest；构建依赖手工 pip 源；CI 不构建镜像、不校验 compose。
- 运维前提：真实证书/域名/备案/微信与智谱凭据/ASR 网关仍未验证，演练报告已如实记录。

### 7.6 前端小程序

**结论：可用性基本达标，发布地址阻断（B-8），交互与无障碍有可见缺陷（P-12/13/14）。**

- 通过：7 页注册完整，4 个 TabBar 图标齐全；11 个 JS 语法全过；危机卡片、订阅消息、语音转写、打卡/日志/练习主流程均有降级与 toast；401 刷新重放约定已实现。
- 不通过：`apiBase` 指向 `127.0.0.1`、`urlCheck:false`；发送失败清空输入；重命名/删除无失败分支；对比度与危机卡片关闭热区不足。
- 说明：同意弹窗不阻塞首页、取消后仍可使用、`consent_prompted` 提前写入，既是合规问题（B-3）也是交互问题。

---

## 八、已确认通过项（正面证据，避免重复返工）

1. 干净快照 `ruff` 全过、`pytest 1009 passed / 1 skipped`（1010 收集）。
2. 小程序 11 个 JS `node --check` 全过；7 页 × 4 文件、4 Tab × 2 图标、sitemap 全部存在。
3. 冻结语料 152/55/137 逐条 0 不符；前九轮定点样本全部保持。
4. 消息/打卡/情绪证据/风险命中词/长期记忆加密；日志与告警不含原文。
5. 鉴权覆盖全部业务路由，公开面仅 health、crisis resources、auth。
6. 生产配置强校验覆盖 9 类危险配置（前提是 `ENV=prod`）。
7. Mongo 不发布宿主端口、强制认证；API 非 root + HEALTHCHECK。
8. high 危机先于模型输出；mid 卡片时序正确；断连继续生成并落库；心跳与缓冲禁用正确。
9. LLM 重试上限真实生效（base 2 次、fallback 1 次），双失败异常链保留备用原因。
10. 合规流式保留窗覆盖规则最大跨度，逐字喂入不漏检；多行替换爆炸半径可控。

---

## 九、必须先清掉的条目（按修复成本排序）

| 顺序 | 条目 | 成本 | 说明 |
|---|---|---|---|
| 1 | B-8 小程序 `apiBase` / `urlCheck` | 分钟级 | 不改就无法连线上，属发布硬门 |
| 2 | B-2 compose 强制 `ENV=prod` + mock 默认关闭 | 分钟级 | 不改可能全校共用同一账号 |
| 3 | B-5 uvicorn 代理头/真实 IP | 分钟级 | 不改登录被全局限流 |
| 4 | B-6 危机链路 try/except + 内置兜底 | 半小时级 | DB 抖动不能丢掉热线 |
| 5 | B-4 标题加密或停止存派生文本（含迁移） | 小时级 | 兑现"对话内容加密"承诺 |
| 6 | B-1 补危机词库表达 + 语料 + 专业复核 | 小时级 | 直接决定首轮能否拦住 |
| 7 | B-7 补合规诊断/疗效规则 + 正反语料 | 天级 | 需误报回归，不能拍脑袋加正则 |
| 8 | B-3 同意状态服务端强制 + 前端路由门 | 天级 | 涉及路由依赖、前端流程与测试 |

完成 1–6 后，系统才具备"小范围内测"的安全底线；7–8 完成后才具备对外提审/上线的合规底线。P 类事项建议与 B 类同批处理，但不构成上线阻断。

---

## 十、复现方式

```bash
# 1) 干净快照
git archive HEAD | tar -x -C /tmp/recheck10

# 2) 独立 venv（镜像源按环境替换）
python3.12 -m venv /tmp/recheck10/backend/.venv
uv pip install --python /tmp/recheck10/backend/.venv/bin/python \
  --index-url https://mirrors.aliyun.com/pypi/simple \
  -r /tmp/recheck10/backend/requirements-dev.txt

# 3) 后端质量门
cd /tmp/recheck10/backend
.venv/bin/ruff check .
.venv/bin/python -m pytest -q

# 4) 语料逐条比对 + 缺口探针
.venv/bin/python /tmp/recheck10/probe10b.py   # 152/55/137，mismatch 全 0
.venv/bin/python /tmp/recheck10/probe10c.py   # B-1 / B-7 缺口

# 5) 小程序门
cd miniprogram
find . -name '*.js' -not -path './node_modules/*' -exec node --check {} \;
```

---

## 十一、结论重申

**当前代码未达到上线标准。** 质量门干净、既有回归未退化，但危机词库召回、生产配置默认值、隐私同意强制、会话标题明文、代理后登录限流、危机链路 DB 耦合、输出侧合规规则、小程序发布地址这 8 项必须先清掉；其中前四项成本极低，不具备延期理由。

在 B-1 至 B-8 全部闭环、且 P-1 至 P-11 中涉及"合规承诺兑现"的条目（物理删除调度、长期记忆兜底、评估门口径）处理完成后，可再次发起上线评估。
