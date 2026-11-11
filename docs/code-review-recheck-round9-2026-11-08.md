# 第九轮完整代码审查报告（2026-11-08）

- 审查对象：`e90f9bf`（`fix(crisis): 词库缓存失效改用 None 状态位，修复重启后热更新失效`），当前远端 `main` HEAD
- 审查范围：以「能否进入上线评估」为准，含前八轮闭环回归、本轮缓存状态位、安全与隐私、危机链路、合规输出、SSE、部署配置、前端小程序、测试有效性
- 取证方式：`git archive HEAD` 导出到 `/tmp/recheck9` 干净快照，独立 venv 仅安装 `backend/requirements-dev.txt`；探针、变异测试全部在仓库外执行。未改业务代码、未提交、未推送
- 对照基线：`a8b71c8`（第八轮 HEAD）
- 说明：本轮质量门结论来自本地实跑，不引用 GitHub Actions run 42472384640 的结论

## 结论速览

| 核查项 | 结论 |
| --- | --- |
| 干净快照 ruff / pytest | 通过：`All checks passed!`、`923 passed, 1 skipped` |
| 前八轮闭环回归（15 条副作用 / 6 条硬边界 / 8 条误报 / 9 条核心） | 通过：15/15、6/6、8/8、9/9 |
| 全量危机语料 123 条 + 记忆语料 44 条 | 0 条不符 |
| 词库缓存 `None` 状态位 | 正确：冷启动、refresh、TTL、并发均按预期；旧写法会被新用例拦住 |
| 缓存并发 / 多实例 / 首轮启动 | 无正确性问题；发现「无 single-flight」与「refresh 仅进程内」两条非阻断行为 |
| 安全与隐私抽查 | 通过：加密落库、日志无原文、生产配置强校验、鉴权覆盖、密钥未入库 |
| 合规输出 | 通过：137 条合规语料随 pytest 全绿 |
| SSE / 危机契约 | 未变：crisis 事件字段、high 先于 delta、心跳 5s < 前端 10s idle |
| 部署配置 | 可用；3 条非阻断硬化项（Dockerfile root、缺 `.dockerignore`、api 无 healthcheck） |
| 前端小程序 | 通过：全量 JS `node --check`；危机卡片字段与后端 payload 一致 |
| 测试有效性 | 通过：新缓存用例在旧实现下，表示断言与行为断言均会红 |

**阻断：0 条。当前代码可以进入上线评估。** 详见第五节。

---

## 一、干净快照与质量门（本地实跑）

```text
$ cd /tmp/recheck9/backend && .venv/bin/ruff check . && .venv/bin/python -m pytest -q
All checks passed!
923 passed, 1 skipped, 1 warning in 3.10s
SKIPPED [1] tests/test_ratelimit_redis.py:170: 未设置 REDIS_TEST_URL，跳过真 Redis 集成测试
```

- 与第八轮（`922 passed`）相比新增 1 条用例，即本轮 `test_refresh_reloads_source_when_monotonic_starts_small`。
- 关键测试文件用例数：`test_crisis.py` 128、`test_redline_regression.py` 556、`test_compliance.py` 35、`test_privacy.py` 7、`test_prod_config.py` 15。
- 唯一 skip 是需真实 Redis 的可选集成测试，CI 通过 `REDIS_TEST_URL` 才会执行；不构成本轮信息缺口。

## 二、前八轮闭环回归

在 `e90f9bf` 快照上用独立探针逐条重跑：

| 回归组 | 结果 |
| --- | --- |
| 第八轮 15 条副作用（14 none + `我不想活\u200b动` high） | 15/15 一致 |
| 第八轮标点/换行硬边界（`〜`、`·`、`「」`、`，`、`。`、换行） | 6/6 为 high |
| 第六轮 8 条误报（活动/活跃/活躍/活蹦乱跳/活跳跳/寻死觅活） | 8/8 为 none |
| 第六轮 9 条核心（含「不想活，走不动了」三条历史漏报） | 9/9 结论不变 |
| 全量危机语料 | 123 条，0 条不符 |
| 全量记忆语料 | 44 条，0 条不符 |

`pytest` 内的 `test_redline_regression.py`（556 条）同时覆盖第一至八轮全部固化样本、原文边界用例与 137 条合规输出语料，全部通过。前八轮闭环项在本轮提交后仍然闭环。

## 三、`e90f9bf` 词库缓存 `None` 状态位

### 3.1 修复正确性

代码变化集中在 [`crisis.py`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L47-L48) 与 [`_load_lexicon`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L259-L290)：

- 初始状态 `_cache["ts"] = None`，`refresh_lexicon_cache()` 也置 `None`；
- 只有 `last is not None` 且 `now - last < 60` 才走缓存，失效状态不再参与时间戳数值比较。

实测（探针把 `monotonic` 固定，排除宿主机 uptime 干扰）：

| 场景 | 实测 |
| --- | --- |
| 冷启动首轮，uptime=5s，`ts=None` | DB 查询 1 次，命中 DB 新词，内置词表仍在并集内 |
| TTL 内（t=5，ts=5；t=59，ts=5） | 新增 DB 查询 0 次 |
| TTL 过期（t=66，ts=5） | 新增 DB 查询 1 次 |
| `refresh` 后，uptime=30s | DB 查询 1 次，旧缓存词不残留，`ts` 更新为当前 monotonic |

结论：原缺陷（主机重启后头 60 秒内 `now - 0.0 < 60` 把已失效缓存误判为新鲜）已被正确修复，且不再依赖宿主机 uptime。

### 3.2 并发刷新

用带 `await` 点的 fake motor cursor 模拟真实交错，20 个协程同时见 `ts=None`：

```text
并发 20：DB 查询 20 次；返回结果一致=True
并发结束后的单次调用：新增 DB 查询 0 次
```

- 无锁、无 single-flight：启动首轮或运营 refresh 后的第一批并发请求会各自回源一次。
- 该查询是 `crisis_lexicon` 小集合的全量 `find`，单次成本低；正常 60s TTL 内只有一次查询，不构成阻断。
- 正确性无问题：所有协程写入的是同一份 DB 并集结果，最终缓存一致。

### 3.3 多实例、TTL 滚动与启动首轮

- **进程内状态**：`_cache` 是模块级 dict，每个 worker/实例独立。`refresh_lexicon_cache()` 只清当前进程，其他实例仍按各自 TTL（≤60s）自然过期。这是既有架构，不是本轮引入。
- **seed 脚本的 refresh 是空操作**：`backend/scripts/seed_crisis.py` 作为独立 CLI 运行，末尾的 `refresh_lexicon_cache()` 只作用于该 CLI 进程，运行中的 API 依靠 TTL 过期获取新词。建议在运维文档中明确「热更新最长 60s 生效」，避免误以为 refresh 立即全局生效。
- **TTL 滚动**：`now` 在 DB 查询前取值、查询完成后以该值写入，极端慢查询会使有效 TTL 略短（可忽略）。
- **启动首轮**：现在保证进程启动后第一次危机检测必读 DB，这正是修复目标；若 `mongo.db is None`（启动时连接失败），仍按内置词表并集缓存 60s，与旧行为一致，不会每请求重试。

### 3.4 测试有效性（变异验证）

在 `/tmp/recheck9` 临时把实现改回旧写法（`0.0` 哨兵 + `now - ts`），分别运行新用例：

1. 保留全部断言：`FAILED ... AssertionError: 失效状态应显式置空`（`assert 0.0 is None`）。
2. 仅删掉表示断言、保留行为断言：`FAILED ... AssertionError: refresh 后仍未回源读 DB（走了缓存）`（返回 `['缓存旧词']`）。

两种变异都会红，说明该用例既能防止状态表示回退，也能防止行为回退；复原后单测通过、全量 923 条通过。

## 四、整体抽查

### 4.1 安全与隐私

- 对话内容应用层加密落库（[`chat.py:76`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L76)）；风险事件命中词加密存储（[`crisis.py:370`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/crisis.py#L370)）。
- 日志抽查：`chat.py` 仅记录字符数、合规规则名等，未记录用户原文或命中词。
- 生产配置强校验（[`config.py:154-191`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/config.py#L154-L191)）：`ENV=prod` 时拒绝 mock 登录、弱 JWT、缺 `DATA_ENCRYPTION_KEY`、无认证 MongoDB、mock ASR 等。
- 鉴权：业务路由共 25 处 `Depends(get_current_user)`；仅 `/health` 与公开求助资源按设计匿名。
- 密钥与治理：仓库内无真实私钥/API Key；`.env` 未入库；根目录 `project.config.json`、`project.private.config.json` 与 `.docx` 均未被 git 跟踪（治理规范要求的禁入项在 HEAD 上是干净的）。

### 4.2 危机链路

- 入口仍是 `detect_risk` / `contains_crisis_terms` / `evaluate` 三处，`e90f9bf` 只改缓存层，不触碰匹配与豁免。
- high：不调用大模型，`crisis` 事件先于任何 `delta`；mid：正常流式，结束后下发危机卡片（[`chat.py:322-324`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L322-L324)、[`chat.py:367-368`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/services/chat.py#L367-L368)）。
- payload 仍为 `{"level", "show_card", "resources"}`，未变。

### 4.3 合规输出

`test_redline_regression.py` 中 137 条合规语料（含跨行流式样例）全绿；`sanitize` 仍按句替换、`detect` 多行委托逻辑未受影响。本轮提交未改合规模块。

### 4.4 SSE

- 心跳默认 5s，小于小程序端 10s idle 超时；`ping` 帧前端按未知事件忽略。
- 生产者任务与 HTTP 连接解耦，客户端断开后继续生成并落库，避免断连丢回复（[`messages.py:35-71`](file:///Users/caspian/Projects/ai-agent/archived/campus-psychological-agent/backend/app/api/routes/messages.py#L35-L71)）。
- `text/event-stream` 不被 nginx gzip，`X-Accel-Buffering: no` 已设置。

### 4.5 部署配置

- `requirements.txt` 全部精确 pin；生产镜像只装运行时依赖。
- `docker-compose.yml`：Mongo 强制认证且不映射宿主端口；nginx 仅在 `prod` profile 启用，证书缺失即启动失败，不降级明文；80 仅跳转 HTTPS。
- 非阻断硬化项：`backend/Dockerfile` 以 root 运行且无 `HEALTHCHECK`；`backend/` 缺 `.dockerignore`，本地 `.env` 会进入 build context（镜像内未 COPY，不影响运行时，但有泄露面）；`SHARED_STATE_BACKEND` 生产未强制 `redis`，单实例部署可接受，多实例需显式配置。

### 4.6 前端小程序

- 干净快照上 `find miniprogram -name '*.js' | xargs node --check` 全部通过。
- `chat.js` 的 `applyCrisis` 按 `payload.level` 生成 high 常驻卡片或 mid 可关闭卡片，`resources` 直传；`crisis-card` 组件字段与后端 payload 一致。

### 4.7 测试有效性

- 全量 923 条通过；新增缓存用例有实际行为断言，不只是断言实现细节。
- CI 的 `eval` job 在未配置 `ZHIPU_API_KEY` 时打印 `SKIP` 并退出 0（脚本注释已说明）。这意味着「CI 三绿」不等于情绪/记忆评估门已实际执行；上线前需确认仓库 secret 已配置并真实跑过一次门禁。属流程提醒，非代码缺陷。

## 五、结论

### 5.1 阻断项

**0 条阻断。**

### 5.2 非阻断项（按优先级）

1. **运维口径（建议上线前写入部署说明）**：`refresh_lexicon_cache` 只清当前进程；多实例/多 worker 下热更新最长 60s 生效；`seed_crisis.py` 末尾的 refresh 对运行中服务无效。
2. **可选性能优化**：缓存回源无 single-flight，启动或 refresh 后的并发首批会重复查询一次小集合；如担心 DB 压力可加进程内锁/单飞，非上线阻塞。
3. **部署硬化**：Dockerfile 增加非 root 用户、`backend/.dockerignore`、api healthcheck；多实例时强制 `SHARED_STATE_BACKEND=redis`。
4. **既有残余（非本轮引入）**：反问/反讽后缀（`我不 想死 才怪`）漏报；`遗书`、单独出现的 `安眠药` 词表覆盖缺口；第八轮报告已记录。
5. **流程**：确认 CI 的 `ZHIPU_API_KEY` secret 已配置，使两个评估门真正执行而非 SKIP。

### 5.3 上线判断

**当前代码可以进入上线评估。** 本轮提交正确修复了重启后词库热更新失效的真实缺陷，前八轮闭环项无回归，安全、危机、合规、SSE、部署与前端契约均未发现阻断问题。
