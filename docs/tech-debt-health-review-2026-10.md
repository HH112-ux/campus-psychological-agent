# 技术债与健康度评估 · 二期中检（面向真实上线）

| 项 | 内容 |
|---|---|
| 评估日期 | 2026-10-29 |
| 评估基线 | `main@b67c346`（V6 长期记忆合入后） |
| 评估方式 | brooks-lint Health Dashboard + Tech Debt Assessment（只读评估，未改动业务代码） |
| 评估范围 | `backend/app`（约 5000 行 Python）、`backend/tests`（25 个测试文件 / 3604 行）、`miniprogram`、部署与配置资产 |
| 关联文档 | `docs/improvement-roadmap.md`（二期路线，§10.3 执行进展）、`docs/brooks-health-report.md`（2026-10-20 基线 92/100）、`docs/versioning.md` |

---

## 一、健康度总览（Brooks-Lint Health Dashboard）

**Composite Score: 91/100**（趋势：92 → 91，基本持平；上期 W1–W4 / S1–S2 已全部闭环，本期新增扣分集中在「上线工程资产」而非代码腐烂）

| 维度 | 得分 | 头号发现 |
|---|---|---|
| Code Quality (PR) | — | 工作区无 diff，按规则跳过（权重重分配） |
| Architecture | 95/100 | 分层仍严格单向（routes → services → core/db），无循环依赖；`docker-compose` prod 编排引用了不存在的 `backend/nginx/` 配置目录 |
| Tech Debt | 84/100 | 部署资产缺口（nginx 配置缺失、Mongo 暴露宿主端口且无认证）+ 文档/Tag 口径再次漂移 |
| Test Quality | 93/100 | 后端 220 passed / 1 skipped（本地，`REDIS_TEST_URL` 未设跳过真 Redis 集成，CI 已配置）；小程序端零自动化测试 |

> 权重（PR 跳过重分配）：Architecture 0.40 · Tech Debt 0.33 · Test Quality 0.27 → 0.40×95 + 0.33×84 + 0.27×93 ≈ **91**。

**一句话结论：** 代码本身的架构纪律与测试纪律在同类项目中属于上游水平；**当前拖分项几乎全部不在代码里，而在「从代码到真实上线之间」的工程资产与外部依赖上**——这与二期路线图「门控项在关键路径」的判断互相印证。

---

## 二、技术债清单（按上线影响分级）

### 🔴 阻断上线（必须在 v1.0.0 提审前清零）

| # | 债务 | 证据 | 影响面 | 修复成本 |
|---|---|---|---|---|
| B1 | **prod 编排引用的 nginx 配置不存在**：`docker-compose.yml` 挂载 `./nginx/nginx.conf` 与 `./nginx/certs`，但仓库无 `backend/nginx/` 目录，prod profile 启动即失败 | [docker-compose.yml](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/docker-compose.yml)（nginx volumes 段）；`ls backend/nginx` 为空 | README 宣称「部署为 docker-compose（FastAPI + MongoDB + Nginx）」，实际不可验证；上线部署链路从未真实跑通 | 0.5–1 天（补 nginx.conf：TLS 终止 + 反向代理 + 限流 + SSE `proxy_buffering off`；证书待 G1 域名） |
| B2 | **域名与 HTTPS 证书未定（G1）**：README Base URL 仍为 `api.xinyu.example.cn [待定]` | README「API 文档 §1」 | 小程序 request 合法域名、提审、B1 证书全部阻塞 | 外部依赖（备案周期不可压缩），**今起并行启动** |
| B3 | **微信提审未走（G2）**：主体/类目未拍板，医疗健康类目资质风险未核实 | roadmap §9 #2 | 上不了线 | 外部依赖，与 M1 运营侧绑定 |
| B4 | **校心理中心电话占位（G3）+ 数据留存期限未谈（G5）** | README §8 求助资源第 4 条 `0XX-XXXXXXXX [待填]`；`config.py` `erase_recover_days=30` 注释「期限口径待 M2 确认」 | 危机转介专业度 + PIPL 留存承诺口径 | 外部依赖（M2），成本最低但最不可压缩 |

### 🟡 高风险（上线后会被放大，建议随 Gate 1 一并处理）

| # | 债务 | 证据 | 影响面 | 修复成本 |
|---|---|---|---|---|
| H1 | **数据导出接口无限流**：`GET /me/data/export` 同步解密导出全部数据，无任何限流；README §15 自认「二期规划，当前未实现限流」 | [users.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/api/routes/users.py#L60-L64)、[privacy.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/privacy.py#L58-L181) | 全量解密 + 大 JSON 响应，被滥用即成本/可用性事故 | 0.5 天（复用 `core/ratelimit` 加 1 次/天/用户） |
| H2 | **MongoDB 生产暴露面**：compose 将 `27017` 发布到宿主且默认 URI 无认证；内网依赖部署纪律，无配置层保障 | [docker-compose.yml](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/docker-compose.yml)（mongo ports 段）、`config.py` `mongodb_uri` 默认值 | 数据库裸奔风险；对话虽应用层加密，但元数据与可用性暴露 | 0.5 天（prod 下去掉 ports 映射 / 绑定内网 + 开启认证） |
| H3 | **高危告警单通道**：`alert_webhook_url` 未配置时仅记 warning 日志，高危事件触达值班人依赖单一企业微信机器人；M4 排班与 SLA 数值仍空 | [alerting.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/alerting.py)、`docs/crisis-response-sop.md`、roadmap §10.3 M4 行 | 高危事件「有人看见」目前不可证明——G11 责任风险未闭环 | 1–2 天（双通道：webhook + 日志文件/邮件兜底；SOP 补排班表并演练一次） |
| H4 | **文档口径再次漂移**：README「pytest 189 项全绿」已过期（实际 220）；`m5` 里程碑 tag 未打（P5 已验收），二期 `m6/m7` 也未打 | README 快速开始第 2 条；`git tag` 仅 m0–m4；`docs/versioning.md` §2 | 「口径单一」原则（roadmap 2.3.5）在执行层失守；发版检查清单无法闭环 | 0.5 小时（改数字 + 补打 tag，须先按 versioning §3 过检查清单） |
| H5 | **小程序后端地址无环境切换**：`app.js` 硬编码 `apiBase: 'http://127.0.0.1:8000'`，发布前需手工改，改错/漏改无防护 | [app.js](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/app.js#L4-L8) | 提审包打错地址=直接驳回或上线即故障 | 0.5 天（构建期注入或 version 配置块 + 提审 checklist 一项） |

### 🟢 可延后（记录观察，不阻塞上线）

| # | 债务 | 证据 | 说明 | 成本 |
|---|---|---|---|---|
| D1 | 小程序 token 明文存 `wx.Storage`（`xinyu_access_token` 等） | [api.js](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/utils/api.js#L10-L29) | 小程序生态常规做法，平台沙箱内风险可接受；access_token 7 天有效期偏长，可后续缩短 | 观察项 |
| D2 | `utils/sse.js` 与 `utils/api.js` 鉴权注入 / 401 处理轻微重复 | [sse.js](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/utils/sse.js#L70-L103) vs [api.js](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/miniprogram/utils/api.js#L98-L140) | Knowledge Duplication，Pain 1 × Spread 2 = 2，Monitored | 0.5 天 |
| D3 | 小程序端零自动化测试 | `miniprogram/` 无测试目录 | 一期策略性取舍（intentional debt）；二期建议至少为 `sse.js` 断帧缓冲补单测（上线后回归痛点） | 1 天 |
| D4 | `config.py` 已 184 行持续增长 | [config.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/config.py) | 尚未构成认知过载，每新增能力 +1 节；观察至 ~300 行再按域拆分 | 观察项 |
| D5 | 微信服务端 token 缓存为进程内 | [wechat.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/wechat.py#L59-L117) | 多实例下各自刷新，stable_token 有并发保护，微信侧允许多 token 并存，影响可忽略 | 不修 |
| D6 | E3 长会话摘要压缩 deferred | CHANGELOG Unreleased 段 | intentional debt，有明确记录与重启前置条件（先扩 E1 评估集），处理得当 | 保持 deferred |

> 历史债务处置确认：2026-10-20 基线报告的 W1（privacy 集合散弹）→ 已由 `user_data_registry.py` 登记表闭环；W2（三处复制）→ `core/llm_json.py` / `core/text.py` / `core/metrics.py` 已收敛；W3（进程内计数）→ `core/counter.py` 双后端；W4（测试顺序依赖）→ conftest 快照还原。PR Review 97/100 的 S1–S3（配置名漂移 / 样板收敛 / TTL 原子化）亦已闭环。**存量代码债处置纪律良好，本期新增债务集中于「上线工程化」。**

### Debt Summary

| Risk | Findings | Avg Priority | Classification | Intent |
|------|----------|-------------|----------------|--------|
| Cognitive Overload | 1（D4） | 1.0 | Monitored | accidental（增长中，未逾阈） |
| Change Propagation | 0 | — | — | — |
| Knowledge Duplication | 1（D2） | 2.0 | Monitored | accidental |
| Accidental Complexity | 2（B1/H2 属「部署资产与宣称架构不符」） | 6.0 | **Critical（上线语义下）** | accidental |
| Dependency Disorder | 0 | — | — | — |
| Domain Model Distortion | 0 | — | — | — |

**Recommended focus：** 代码内六类衰变风险基本无系统性问题；债务焦点在代码外的「上线工程资产」与「外部依赖门控」。

---

## 三、上线门控风险评估

### 3.1 合规与安全

| 检查项 | 现状 | 结论 |
|---|---|---|
| 密钥管理 | `.env` 不入库 + `.env.example` 模板 + `ENV=prod` 启动 fail-fast 校验六项危险配置（[config.py](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/config.py#L149-L179) `_validate_prod_config`）；全仓 `git ls-files` 无密钥/私钥入库 | ✅ 健康 |
| 日志脱敏 | 抽查 emotion / long_memory / speech / wechat / alerting：日志仅含 ID、条数、字节数，无对话原文、无 token、无 openid 明文（mock 登录记 `code[:8]`） | ✅ 健康 |
| 数据加密 | 对话 content 与长期记忆 AES-256-GCM 应用层加密（`core/crypto.py`），导出时服务端解密 | ✅ 健康 |
| 内容安全 | msgSecCheck 已接入 `_pre_turn`，命中 2006 不落库（M1 技术侧 ✅） | ✅ 健康 |
| 物理删除承诺 | `purge_expired_data()` 已挂 lifespan 调度 + 有到期删除测试（M3 ✅）；但**留存期限数值（30 天）未经校方确认**（G5） | 🟡 机制就绪，口径待定 |
| 数据导出行权 | 已实现但**无限流**（H1） | 🟡 需补 |
| Mongo 暴露面 | 见 H2 | 🔴 上线前必修 |
| 隐私政策/同意 | `docs/privacy-policy.md` + 同意弹窗链路在；政策版本 `PRIVACY_POLICY_VERSION = "1.0"` | ✅ 健康 |

### 3.2 危机干预红线

| 红线 | 现状 | 结论 |
|---|---|---|
| 不诊断 / 不推荐药物 / 不宣称治疗 | 系统提示词与练习卡片均守边界；周报洞察有「不得出现因为/导致/由于」的测试强制断言 | ✅ 有测试兜底 |
| 危机词库召回 ≥95% | 一级 79 条本地词库，不依赖模型，60s TTL 热更新 + 内置兜底；模型 risk_level=high 双保险（`handle_model_risk`）；词库漏报信号已接告警 | ✅ 机制完备 |
| 高危只转介不处理 | high 路径不调大模型，固定话术 + 求助卡片先于 delta 下发 | ✅ 架构级保障 |
| 高危事件人工响应 | 告警链路代码完成（M5 ③），**但 M4 排班/SLA 未落实，告警单通道**（H3） | 🔴 责任闭环缺口——这是评委与校方最可能追问的点 |
| 求助资源 | 第 4 条校心理中心电话仍占位（G3/B4） | 🔴 上线前必填 |

### 3.3 可用性与成本

| 项 | 现状 | 结论 |
|---|---|---|
| 模型容灾 | E2 完成：GLM 主 + 通义千问备，FallbackProvider 语义严格；E3 启发式路由默认关 | ✅ 单供应商风险已解 |
| 超时与降级 | 主对话 30s 超时 + 重试 1 次 + 降级话术；情绪分析 5s 硬超时失败不阻塞；ASR 未配置 fail-safe 回键盘输入 | ✅ 降级语义清晰 |
| 成本 | `core/cost.py` 基线计数（100 次一条结构化日志）；约 0.02 元/天/用户量级 | 🟡 有基线无周报机制（M5 ④ 未做）；摘要压缩 deferred 合理 |
| 限流 | memory/redis 双后端（M5 ① ✅），生产置 redis 即跨实例生效 | ✅ 代码就绪，待部署 |
| 真实部署验证 | **从未跑通过**（B1 nginx 缺失 + G1 域名未定 + compose prod 未启用） | 🔴 上线前最大未知 |
| 测试门 | 后端 220 passed；CI 含 ruff + pytest + mongo/redis 服务容器 + eval gate；**小程序端无测试**（D3） | 🟡 后端强，前端裸奔 |

---

## 四、二期下一步：三个可选方向

### 方向 A · 上线冲刺（清空 Gate 1 剩余门控）

- **目标**：让「真实上线」从「代码就绪」变成「部署可跑通 + 提审材料齐备」。
- **内容**：B1 补 nginx 配置并**真实跑通一次 prod compose 部署**（哪怕先在无域名内网环境验证链路）；G1 域名备案与证书申请启动；G2 主体/类目核实 + 提审材料定稿；H5 小程序环境切换；H4 口径修正 + 补打 m5/m6/m7 tag。
- **预计工作量**：开发 3–5 天；外部等待（备案/微信审核/校方）2–6 周不可压缩。
- **主要风险**：备案与类目审核节奏不受控；校方回复延迟。
- **最小可验证里程碑**：`ENV=prod docker compose --profile prod up` 在内网服务器一次启动成功，`/health` 经 nginx + HTTPS 返回 200，全链路（登录→对话→危机拦截）真机走查通过。
- **与 8 周路线/二期目标关系**：即阶段一「上线必需」（m6 / v1.0.0）的收尾，是关键路径本身。

### 方向 B · 运营韧性（让「上线后不出事」可被证明）

- **目标**：把 M4 从「草案 + 告警代码」变成「演练过的响应链」，补齐剩余高风险债。
- **内容**：H3 告警双通道 + SOP 排班表落地并**实战演练一次**（模拟一级词命中 → 值班人收到 → 按 SOP 处置 → 48h 复盘留痕）；H1 导出限流；H2 Mongo 收敛暴露面；M5 ④ 模型成本周报脚本化；D3 为 `sse.js` 断帧缓冲补单测。
- **预计工作量**：2–3 天开发 + 半天演练。
- **主要风险**：SOP 涉及校方人力资源，依赖 M2 进度；演练暴露的流程问题可能返工。
- **最小可验证里程碑**：一次有记录的高危事件演练复盘文档（含触达时延实测值）；`pytest` 新增导出限流用例全绿。
- **与路线关系**：M4/M5 的完成定义（roadmap §3.3 验收标准「演练一次」），是 Gate 1 验收的一部分。

### 方向 C · 体验验证冲刺（内测数据驱动迭代）

- **目标**：在内测人群上验证「用过的人还愿意再用」，为上线后迭代攒数据资产。
- **内容**：跑通 V1 双周 bad-case 复盘节奏（导出 → 归因 → 提示词/词库迭代 → E1 回归门）；基于内测反馈决定 E3 摘要压缩或 V7 量表自评预研是否启动；小程序关键链路（SSE 中断恢复、401 静默续期）体验走查清单化。
- **预计工作量**：持续机制，首轮 2 天启动。
- **主要风险**：内测样本量不足时复盘结论失真；V7 量表涉「打分+建议」诊断嫌疑，须先过 M2 口径。
- **最小可验证里程碑**：第一期 bad-case 复盘报告（至少 1 个可归因迭代项过 E1 回归门）。
- **与路线关系**：roadmap 第六章「持续迭代机制」的首次实转；属阶段二（m7 / v1.1.0）的使能动作，可在 Gate 1 等待外部方期间并行。

---

## 五、推荐路线

**主线：方向 A（上线冲刺）。** 二期所有代码侧使能项（E1/E2/E3）与增值项（V1–V6）已交付，当前唯一卡住「真实上线」的就是部署链路从未真实验证 + 外部门控未清空；方向 A 直接作用于关键路径，且 B1（nginx 补齐 + 真实部署一次）是全部剩余风险中「完全由我方可控、成本最低、信息增益最大」的一项——建议作为下周第一件事。

**可选加分项：方向 B 中的「M4 实战演练一次」。** 半天成本，把「高危事件有人响应」从承诺变成有留痕的证据，同时顺带验证告警链路真实可用——这是性价比最高的信任资产。

**并行原则**：A 的外部等待期（备案/审核）正是 C 的 bad-case 复盘首轮与 D3 前端测试补强的窗口，不占用关键路径。

### 评委最可能追问的 3 个薄弱点与补强

| # | 追问点 | 现状弱点 | 补强方式 |
|---|---|---|---|
| 1 | **「高危事件发生时，谁、多久、怎么响应？」** | SOP 是草案，排班/SLA 空白，告警单通道（H3）；只有技术链路，没有「人」的证据 | 方向 B 演练一次并留痕：触达时延实测、处置记录、48h 复盘文档；回答时用演练数据而非设计图 |
| 2 | **「你们说数据加密、到期删除，怎么证明？」** | 机制都有测试，但留存期限 30 天未经校方确认（G5），承诺口径悬空 | 把 G5 纳入 M2 谈判清单并拿到书面确认；答辩时展示 `test_purge_expired_data` 与 `user_data_registry` 登记表作为「承诺可被测试证明」的样板 |
| 3 | **「这东西真的部署过吗？」** | prod compose 从未跑通（B1），域名占位（G1），README 宣称的 Nginx 拓扑无配置实体 | 方向 A 的内网真实部署走查 + 录屏/日志留档；哪怕域名未下，也要有一次「非 localhost」的完整链路证据 |

---

## 六、附：评估方法与局限

- 本次为**只读评估**，未修改任何业务代码；发现的小问题（README 过期数字、缺 tag 等）仅记录于本报告。
- pytest 为本地只读运行（220 passed / 1 skipped，skip 为 `REDIS_TEST_URL` 未设的真 Redis 集成用例，CI 已配置该项）。
- brooks-lint 历史：`.brooks-lint-history.json` 已追加本次记录；前次 Health 92/100（2026-10-20）、PR Review 97/100（2026-10-26）。
- 未覆盖：智谱/通义真实 API 行为（无 key 环境下评估集 SKIP）、微信侧真实提审规则（以官方最新规则为准）。
