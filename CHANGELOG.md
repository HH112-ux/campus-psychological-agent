# 变更日志

本文件记录「心屿」项目的所有重要变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循[语义化版本](docs/versioning.md)。

## [Unreleased]

### 二期门控项（M3 · M4 · M6）

- **M5 ③ 监控告警 MVP + M4 值班人通知链路**：新增 `services/alerting.py`——企业微信群机器人 webhook（未配 URL 仅记 warning 日志），同一 key 冷却去抖（`ALERT_COOLDOWN_SECONDS`，默认 600s），异常永不抛出；三处敏感点接入：高危风险事件通知值班人（`record_risk_event` level=high）、模型兜底命中追加词库漏报信号（`handle_model_risk`）、LLM 重试失败降级告警（`chat.py` 非流式/流式三处返回点）。隐私红线：告警只含用户/会话 ID、级别与触发源，不含命中词与对话原文。新增 9 项测试（`test_alerting.py`）。

- **M5 ⑤ dev/prod 密钥分离落实**：`Settings` 新增生产配置启动校验（`ENV=prod` 时 fail-fast）——mock 登录、缺 AppID/Secret、内容安全关闭、弱 JWT（默认或 <32 位）、缺加密密钥、缺模型密钥 六类危险配置直接拒绝启动并列出全部问题；`main.lifespan` 对「prod + 内存限流」追加启动告警日志；新增 8 项测试（`test_prod_config.py`），dev/测试默认配置不受影响。

- **M5 限流生产化（G4）**：限流重构为内存 / Redis 双后端——`RATELIMIT_BACKEND=memory|redis` 配置切换，业务代码零改动；Redis 后端为 ZSET 滑动窗口 + Lua 原子判定（被拒请求不占窗口、key 自动 TTL），跨实例共享计数；Redis 不可达 fail-open；lifespan 关闭连接。新增 `redis==5.2.1` 依赖与 8 项测试（含真 Redis 集成，CI 挂 redis:7 service，本地经真 Redis 验证全绿；全量 **97 passed**）。

- **E1 评估与回归门**：`eval_emotion_p5.py` 新增 `--gate` 阈值门（严格一致率 < 80% 退出 1；未配置 `ZHIPU_API_KEY` 时打印 SKIP 退出 0）；CI 新增 `eval` job（secret 注入后转为真门，未配置不阻塞）；新增 `docs/eval-gate.md`（用法 + 「新增 LLM 能力 → 新增评估样本」扩充约定）；本地真跑 GATE PASS 88.1%（滚动基线已刷新）。

- **M1 技术侧：微信内容安全接入（G9）**：用户消息入库前过微信 `msgSecCheck` v2——新增 `app/services/content_security.py`（suggest=risky 或 errcode=87014 拦截返回 `code=2006`，不落库不计限流；review 放行；接口异常 fail-open；token 失效强制刷新重试一次）；`wechat.py` 新增 `get_access_token()`（stable_token 内存缓存 + 提前 300s 过期 + 锁防并发刷新）；开关 `WX_CONTENT_CHECK_ENABLED`（mock 登录或未配置 AppID/Secret 自动跳过，生产必须为 true）；新增 8 项测试（`test_content_security.py`）。
- **会话上限调整（M6+）**：并发活跃会话上限由 3 调整为 **5**（UX 评估：3 对多话题并行偏紧；5 兼顾体验与成本/内存控制），`config.py` / `.env.example` / README / API 文档 / 小程序 README / roadmap 口径同步。
- **M6 口径与文档对齐**：会话并发上限由代码默认 `15` 对齐为 **`3`**（与 README / API 文档 / `.env.example` 一致，G8）；修正 README 与 API 文档中「数据导出（二期实现 / 异步任务）」的过期描述为「同步返回 JSON，限流为二期规划」（G10）。
- **M3 合规承诺兑现**：`privacy.purge_expired_data()` 接入调度——新增 `run_purge_scheduler()`，由 `main.lifespan` 以 asyncio 任务启动、进程退出时取消（G7）；留存期限与开关可配置（`ERASE_RECOVER_DAYS` / `DATA_PURGE_ENABLED` / `DATA_PURGE_INTERVAL_SECONDS`）；新增 `test_purge_expired_data` 证明「恢复期未满不删、到期全量物理删除（含消息）」。
- **M4 人工响应 SOP（草案）**：新增 `docs/crisis-response-sop.md`，定义高危事件的触发条件、值班角色、SLA、升级路径与留痕隐私红线（校方联系人、SLA 数值等待 M2 / 运营补齐，G11）。
- **二期路线规划**：新增 `docs/improvement-roadmap.md`（v1.1），确立三轨道（门控 M / 使能 E / 增值 V）与「门控项置于关键路径」的排期原则。

### 增值项（V1 反馈闭环）

- **V1 bad-case 复盘机制**：把已收集的点赞/点踩从「只收集不迭代」升级为闭环——“收集 → 复盘 → 迭代 → 回归验证”。新增 `app/services/bad_cases.py`（收集点踩回复，按时间序配对触发它的用户消息、解密内容、关联会话标题，并按原因聚合计数）+ `scripts/export_bad_cases.py`（近 14 天 / 自定义窗口 / 全量导出，支持 `--out` 落文件）+ `docs/bad-case-review-template.md`（逐条归因表 + 迭代项汇总 + 闭环健康度自检，留档不粘贴原文）。隐私：导出文件含解密对话内容，`.gitignore` 新增 `bad-cases*.json` 防御规则。新增 3 项测试（`test_bad_cases.py`）。

### 增值项（V2 周报洞察）

- **V2 本周情绪小结**：基于与 `trends` 同源的聚合数据，服务端生成「本周情绪小结」（新增 `GET /api/v1/emotion/weekly-insight`，复用 `emotion_logs` 聚合逻辑，不新增数据采集）——覆盖记录覆盖天数/条数、主导情绪、主导情绪的**时段分布**（早上/下午/晚上/深夜）、与上周强度对比、打卡天数，并拼装为中文短句列表 `highlights`，小程序情绪日志页以小结卡渲染。红线：只输出**描述性**结论（如「焦虑多出现在晚上」），**严禁归因断言**（不出现「因为 / 导致 / 由于」类因果句式，测试断言强制校验）。附带修复：`emotion_logs` 时区归一（`_to_cst`）——motor 读回的 `created_at` 为 naive UTC，此前 `trends` 按 UTC 分桶存在 8 小时偏移（深夜记录被错分前一日/下午），现统一转为业务时区后再分桶/判时段。新增 4 项测试（`test_emotion.py` 周报洞察段）。

### 增值项（V3 主动关怀）

- **V3 主动关怀**：基于情绪日志的主动问候——新增 `app/services/caring.py`，每日在 `CARING_HOUR`（默认 9 时，`main.lifespan` 启动调度、进程退出取消）扫描候选用户（未软删 / 未关闭关怀 / 仍有订阅配额），命中触发条件即经微信订阅消息发送温和问候：① 连续 `CARING_LOW_STREAK_DAYS` 天负面档位（low/anxious/irritable，`low_streak`）；② 打卡中断 `CARING_CHECKIN_GAP_DAYS` 天（`checkin_gap`）。**授权门槛**：仅对 `care_subscribe_count > 0`（一次性订阅每次授权 +1，发送扣减一次）发送；**频控**：同一用户每周最多 `CARING_MAX_PER_WEEK`（默认 2 条），依据 `care_messages` 留档计数；文案为温和邀请、避免说教/命令句式（复用 bad-case `preachy` 负面样本，测试断言红线）。新增 `wechat.send_subscribe_message()`（stable_token 复用 + token 失效强刷重试 + mock 占位）；用户侧接口 `GET/PUT /api/v1/users/me/caring` + `POST /api/v1/users/me/caring/subscribe`（随时开关 + 回填授权结果）。**隐私基线**：`care_messages` 留档仅记触发类型/状态，不含问候原文与情绪证据；数据导出与到期物理删除均纳入该集合。**fail-safe**：未配置订阅模板 ID（`WX_SUBSCRIBE_TEMPLATE_ID`，微信侧外部依赖）时安全跳过，不影响主链路与调度。新增 13 项测试（`test_caring.py`），全量 **135 passed**。

### 增值项（V4 练习卡片）

- **V4 练习卡片**：把提示词里已有的「身体优先 / 呼吸练习」话术产品化——新增 `app/services/practices.py` 内置卡片目录（4-7-8 呼吸 / 箱式呼吸 / 三分钟呼吸空间 / 微小行动），分类 `breathing`（配 `pattern` 驱动呼吸动画）/ `mindfulness`（`steps` 分步引导）/ `activation`（`tasks` 行动清单）。新增接口 `GET /api/v1/practices`（目录 + 今日已完成标记）与 `POST /api/v1/practices/{id}/complete`（完成反馈落库 `practice_logs`，同日可多次、缺省用建议时长；未知 id 返回 2001）。小程序新增 `pages/practice/practice`（呼吸引导缩放动画 + 正念分步计时 + 行动清单勾选），入口位于首页与「我的」页；练习完成记录已纳入数据导出与到期物理删除。**内容边界**：仅做放松/觉察引导，不含诊断/治疗/疗效表述，卡片均标 `reviewed=false` **[待专业审校]（联动 M2 心理中心老师）**。新增 5 项测试（`test_practices.py`，含文案红线与内容断言），全量 **140 passed**。

### 仓库治理与 CI

- **规范对齐与升级**：`docs/repo-governance.md` 补齐「CI 与质量门」章、命名豁免清单、根目录清洁规则与 Push Checklist（新增敏感/产物复查）；HTML 文档包（`campus-agent-*-doc/*.html` + `_shared/` + `assets/`）移出仓库，**`.md` 为唯一入库来源**。
- **命名整改**：`backend/scripts/eval_data/` → `eval-data`（同步脚本与文档引用，含 `eval_emotion*.py` / `build_eval_v2.py` 与两处评估留档）。
- **CI 落地**：新增 `.github/workflows/ci.yml`（后端 `ruff check` + `pytest`，含 MongoDB 服务容器；小程序全量 JS `node --check`），补上写了但未落地的质量门。
- **清理与配置**：删除根目录游离的 `project.config.json`（真身在 `miniprogram/`）；`.gitignore` 去重并新增 HTML 文档产物忽略规则；README 补仓库结构说明与「保留所有权利」许可声明（暂不提供 `LICENSE`）。

### 新增

- P4 对话内容应用层加密：AES-256-GCM（`app/core/crypto.py`），密钥 `DATA_ENCRYPTION_KEY`（base64url 32 字节）；dev 未配置时透明存储、prod 强制要求；消息落库加密、读取解密，明文老数据兼容平滑迁移；日志脱敏 `redact`。
- P4 模型危机双保险：情绪分析 `risk_level=high` 时，即使本地词库未命中也写 `risk_events`（trigger=model）并升级会话 `crisis_high_shown`；SSE 流在 emotion 事件后追加 crisis 事件（携带求助资源，触发时机在 delta 之后、done 之前）。
- P4 隐私与数据权利：`POST /users/me/consent`（记录隐私同意+政策版本）、`GET /users/me/data/export`（PIPL 行权，导出用户/会话/消息/情绪/打卡/风险事件，对话内容解密后导出）、`DELETE /users/me/data`（软删 + 30 天可登录撤销，期满物理删除，须输入「删除」确认）。
- P4 测试：`test_crypto.py`（加解密往返/明文兼容/密钥校验）、`test_privacy.py`（consent/export/erase 接口与 400 拒绝路径）。
- P5 评估与提审准备：
  - 评估集扩充至 **59 条**（`emotion_eval_v2.json`：四类 14/17/16/12 + 对抗 11，含黄金强度标注）；
  - 情绪分析提示词迭代 **V2**（低落/焦虑边界、平静/还行区分、反讽/引用识别），版本对比见 `docs/prompt-eval-v1-v2.md`；
  - P5 正式评估（`docs/emotion-eval-p5.md`）：**严格一致率 86.4%（≥80% 达标）、强度 MAE 1.37（≤2 达标）、对抗样本 11 条**；
  - 危机词库扩充暴力他人类（一级强信号 55→79 条），危机召回测试 34 项全绿，留档 `docs/crisis-recall-p5.md`（≥95% 一票否决通过）；
  - 降级开关：`EMOTION_ANALYSIS_ENABLED`、`STREAM_ENABLED`（config + 链路接入 + 测试）；
  - 压测与成本：/health 200req@50并发 3816 req/s P95 30ms；对话整轮 ~5.2s；单用户日成本 ≈0.02 元（`docs/eval-cost-p5.md`）；
  - 隐私政策终稿（`docs/privacy-policy.md`）、提审材料包（`docs/review-package-p5.md`）、内测方案（`docs/beta-plan-p5.md`）；
  - 小程序隐私单独同意弹窗（首次启动 + 「我的」页重新同意入口）。

- 仓库基线：开发文档、API 文档、贡献规范（CONTRIBUTING）入库，建立 main 分支与 m0 里程碑。
- 任务拆分规范：按 F1–F6 功能编号拆分任务，关联阶段与 API 接口（docs/task-management.md）。
- 版本与发布策略：SemVer + m/v 双 tag 规则（docs/versioning.md）。
- 危机词库变更流程：五步闭环 + 回滚 + 误报反馈闭环（docs/crisis-lexicon-workflow.md）。
- 安全策略：漏洞报告、密钥管理、依赖安全、数据保护与应急响应（SECURITY.md）。
- P0 后端脚手架：FastAPI 应用入口、统一响应/异常、配置中心（pydantic-settings）、motor 连接与 8 个集合索引、智谱 LLM Provider（含 SSE 流式）、`/health` 路由、init_db/test_llm 脚本、pytest 与 ruff 配置、Dockerfile 与 docker-compose。
- P0 小程序占位工程：原生框架可编译启动，占位首页含 `/health` 连通性检测。
- P0 验收：`GET /health` 返回 200 且 `db: connected`，pytest 3 项全绿，ruff 无 error；智谱 `glm-4-air`（主对话）/ `glm-4-flash`（轻量）双档位真实调用均已实测返回。
- P1 认证：微信 `wx.login` → `code2session` 换 openid（支持真机与本地 `WX_MOCK_LOGIN` 双模式）、JWT 双令牌（access 7 天 / refresh 30 天）、refresh 旋转即旧 token 作废、`/users/me`；openid 只存服务端，不写入令牌也不下发。
- P1 会话：列表/创建/详情/重命名/删除，强制 `user_id` 隔离（跨用户统一 404，不暴露存在性）；单用户活跃会话上限 3、单会话轮次上限 50、首条消息前 12 字自动回填标题。
- P1 对话（MVP 核心）：非流式与 SSE 流式（`meta → delta → crisis → done / error` 帧）、提示词 V1（共情陪伴 + 单次 ≤120 字）、近 20 轮窗口记忆、模型超时/异常重试 1 次后降级为固定话术；流式按块间隔判超时。
- P1 危机红线：本地两级词库同步拦截器（不依赖模型），内置 55 条一级强信号（命中即 high，不调大模型，直接固定危机话术）+ 33 条二级语境词（每命中一个不同词 +2、会话累计 ≥4 升 high）；覆盖空格/标点/符号、拼音与网络谐音等基础变体；高危卡片置顶常驻、mid 卡片流后插入，4 条求助热线并支持一键拨打；所有 mid/high 写 `risk_events`（仅记命中词与 lexicon 来源，不存原文），会话删除后风险事件仍留存审计。
- P1 反馈：助手回复点赞 / 点踩（点踩必须选择原因）。
- P1 限流：内存固定窗口单机内测（登录 10 次/分/IP、消息 30 条/时/用户、读 60 次/分/用户），代码注释标注生产需替换为 Nginx/Redis。
- P1 小程序：静默登录封装（自动携带 JWT、401 静默刷新并自动重放）；SSE 流式对话页（`enableChunked` + 跨 chunk 安全 UTF-8 解码、按 `\n\n` 断帧、10s 无增量中断、旧基础库自动降级非流式）；高危卡片置顶常驻 / mid 卡片插入流、一键拨打热线；会话列表（新建/进入/重命名/删除）；高危卡片在重进会话时依据 `crisis_high_shown` 恢复。
- P1 测试：后端 46 项 pytest 全绿（28 项危机红线用例含 18 个高危变体与 6 个防误报、15 项 P1 认证/会话/消息集成测试 mock LLM、3 项 P0），ruff 无 error；小程序 SSE 解码经 Node 模拟逐字节/分块/大块三种切分验证通过。
- P2 小程序完整页面：四 TabBar 结构（首页/对话/情绪日志/我的）按原型落地；首页打卡 + 开始倾诉入口、对话页输入框长度限制（2000 字）与键盘适配（adjust-position + 安全区）、会话列表（新建/继续/重命名/删除/空态）、等待/网络错误/空列表三状态、登录态过期静默续期（401 刷新重放）；日志时间线条目支持"定位到来源对话"（records 返回 session_id）与"当日打卡备注编辑"（复用 upsert 接口）；全流程（打卡 → 倾诉 → 看历史 → 删除会话）API 链路验证无阻塞缺陷。
- P3 情绪识别管道：轻量模型 `glm-4-flash` 对本轮消息（含前两轮上下文）输出结构化 JSON（六类情绪 + 强度 1-10 + evidence + risk_level + strategy_hint），5s 预算内完成，失败不阻塞回复、不写错误数据（宁可缺失）；结果回填 assistant 消息 emotion 字段并写入 `emotion_records`；SSE 新增 `emotion` 事件（delta 全部下发后、done 之前），非流式响应带 `emotion` 字段；策略层按最近情绪注入身体优先 / 转介等话术。
- P3 每日打卡：五档情绪（calm/ok/low/anxious/irritable → 强度 2/4/6/7/6）按「用户 + 日期」upsert、连续天数 streak、记忆型问候（按最近情绪记录套固定模板，不调大模型）；`/users/me` 扩展 `checkin_streak` + `memory_greeting`。
- P3 情绪日志：`GET /emotion/records`（对话 + 打卡双来源合并、情绪筛选、时间倒序分页、会话标题两跳关联、打卡 mood 归一化到六类枚举）；`GET /emotion/trends`（day/week/month 粒度、7/30 天窗口、日均强度与上周对比、主导情绪、无记录置 null 不补 0）。
- P3 小程序：四 TabBar（首页/对话/情绪日志/我的）；首页按时段问候 + 每日一句 + 记忆型问候 + 五档打卡；情绪日志页 7 天趋势柱状 + 时间线 + 情绪筛选；对话页情绪角标（本轮识别：焦虑 · 7/10）；「我的」历史会话 + 求助热线 + 免责声明。
- P3 一致率首次测量留档：45 条离线评估集（四类各 10 + 5 条反讽/引用对抗样本），`docs/emotion-eval-m3.md` 记录 86.7% 总一致率、按类一致率与不一致明细（P5 将扩充至 ≥50 条并作为 go/no-go 依据）。
- P3 测试：后端 62 项 pytest 全绿（新增 16 项：解析正反例含管道值容忍、打卡 upsert/streak/校验、情绪落库与回填、SSE emotion 事件时序、策略层注入、时间线合并筛选、趋势聚合含纯打卡来源、users/me 问候、双用户隔离），ruff 无 error；小程序全部 JS 通过 node --check。

