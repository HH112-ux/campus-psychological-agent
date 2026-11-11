# LangChain 迁移计划（模型调用层）

- 日期：2026-11-11
- 基线：`1114 passed, 1 skipped`，`ruff check .` 通过
- 适用仓库：`campus-psychological-agent`
- 结论先行：**只迁移模型调用层**（`ZhipuProvider` / `QwenProvider` 的 HTTP 传输），不引入 LangChain 的 chain、memory、agent、retriever；`LLMProvider` 接口、`FallbackProvider`、路由、SSE 与全部确定性链路保持原样。

## 0. 实施状态（2026-11-11，已完成）

**状态：已完成。** P0–P2 全部落地，GLM 主通道已用真实端点验证（见第 10 节），
迁移前基线 `1114 passed, 1 skipped` → 迁移后 `1128 passed, 1 skipped`，`ruff check .` 全程通过。

| 阶段 | 提交 | 结果 |
|---|---|---|
| P0 依赖与适配模块 | `5872488` | `langchain_client.py` + 9 例单测；`1122 passed, 1 skipped` |
| P1 provider 切换传输层 | `7cafcd3` | 手写 httpx/SSE 下线；`test_llm_transport.py` 5 例；`1127 passed, 1 skipped` |
| P2 文档与边界守卫 | `1ecc3ef` | README 技术栈对齐；`test_llm_boundary.py` 1 例；`1128 passed, 1 skipped` |

实施中发现的额外缺陷：`langchain-openai 1.x` 会把请求体里的 `max_tokens` 改名为
`max_completion_tokens`，而智谱 v4 与 DashScope compatible-mode 只认 `max_tokens`
（被忽略则失去回复长度上限，被拒绝则整链路不可用）。已在 `ChatOpenAICompat` 的
请求体层还原字段名，并由 `test_request_payload_keeps_max_tokens_field` 锁定。

仍未覆盖：DashScope 备用通道未验证（`.env` 未配置 `QWEN_API_KEY`，`qwen_enabled` 默认关闭）；
GLM 主通道已用真实端点验证，见第 10 节。

## 1. 真实盘点（非估算）

### 1.1 现有抽象

| 文件 | 行数 | 职责 |
|---|---:|---|
| `backend/app/llm/base.py` | 22 | `LLMProvider` 抽象；`generate` / `stream`；`max_attempts`（默认 2） |
| `backend/app/llm/__init__.py` | 39 | 工厂：`get_chat_provider()` / `get_light_provider()`；按 `qwen_enabled` 决定是否包 `FallbackProvider` |
| `backend/app/llm/router.py` | 55 | 启发式分档 `select_tier()` / `provider_for_tier()` |
| `backend/app/llm/fallback.py` | 88 | 主备容灾；`max_attempts = 1`；流式仅“未产出任何 chunk”时切备 |
| `backend/app/llm/zhipu.py` | 82 | 智谱 v4（OpenAI 兼容）HTTP 实现，手写 SSE 解析 |
| `backend/app/llm/qwen.py` | 95 | DashScope compatible-mode HTTP 实现，手写 SSE 解析 |
| 合计 | 381 | — |

### 1.2 LLM 调用点（共 4 处）

| # | 文件:行 | 调用 | 档位 | 用途 |
|---|---|---|---|---|
| 1 | `backend/app/services/chat.py:213` | `provider.generate(...)` | 主/轻 | 非流式对话回复（`temperature=0.7`，`max_tokens=400`） |
| 2 | `backend/app/services/chat.py:251` | `provider.stream(...)` | 主/轻 | SSE 流式对话回复（同上参数） |
| 3 | `backend/app/services/emotion.py:194` | `provider.generate(...)` | 轻量 | 情绪分类（`temperature=0.1`，`max_tokens=100`，外层 `wait_for(5s)`） |
| 4 | `backend/app/services/long_memory.py:223` | `provider.generate(...)` | 轻量 | 长期记忆抽取（`temperature=0.2`，`max_tokens=300`，外层 `wait_for(8s)`） |

**“标题生成”不是模型调用**：`chat.py` 首轮把用户首句截断为 12 字作为标题，无 LLM 参与。迁移不涉及。

### 1.3 流式与断连

| 机制 | 位置 | 现状 |
|---|---|---|
| 心跳 | `messages.py:60 _with_heartbeat` | 每 `sse_heartbeat_seconds`（默认 5s）下发 `ping` 帧 |
| 生成与连接解耦 | `messages.py:73 _produce` | 生成跑在独立 task，客户端断开只停止读取，生成继续 |
| 截断标记 | `chat.py:321/345-349/396` | 已产出后失败 → `truncated=true`、`degraded=true`、告警 `stream_truncated` |
| 断连落库 | `chat.py:397-405` | `finally` 中把已生成文本（或兜底话术）通过后台任务 `_finalize` 落库 |
| 高危短路 | `chat.py:326-333` | `crisis.level == high` 不调用模型，直接返回热线话术 |

以上全部位于模型层之外，迁移不得改动。

### 1.4 超时、重试、降级

| 语义 | 现状 |
|---|---|
| 超时 | `httpx.Timeout(read=model_timeout_seconds=30s, connect=10s, write=10s, pool=10s)` |
| 重试 | 调用层 `for _ in range(provider.max_attempts)`：裸 provider 2 次；`FallbackProvider` 1 次 |
| 主备 | `qwen_enabled=true` 且 key 非空时 `ZhipuProvider → QwenProvider`；备用也失败时重抛主异常 |
| 空响应 | 流式视为失败并重试；重试耗尽抛 `_StreamUnavailable` |
| 错误传播 | provider 抛任意 `Exception`，由 `chat.py` 统一降级；`asyncio.CancelledError` 不被吞 |

### 1.5 测试替身涉及面

| 测试文件 | provider 打桩行 | 用例数 |
|---|---:|---:|
| `test_alerting.py` | 6 | 9 |
| `test_chat.py` | 9 | 11 |
| `test_compliance.py` | 2 | 14 |
| `test_content_security.py` | 8 | 8 |
| `test_cost_routing.py` | 26 | 20 |
| `test_degrade_switches.py` | 5 | 2 |
| `test_emotion.py` | 10 | 21 |
| `test_llm_fallback.py` | 15 | 15 |
| `test_long_memory.py` | 16 | 22 |
| **合计** | **33 行 / 9 文件** | **122** |

替身方式全部是 `monkeypatch.setattr(<模块>.ZhipuProvider, "generate"/"stream", fake)`，**没有任何用例断言 HTTP 请求体、headers、`_timeout` 或解析细节**。因此只要保留类名与方法签名，33 处打桩零改动。

## 2. 迁移范围与理由

### 采用

- `langchain-openai` 的 `ChatOpenAI` 作为统一传输层，指向现有 OpenAI 兼容端点：
  - 智谱：`https://open.bigmodel.cn/api/paas/v4`
  - DashScope：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- 仅替换 `ZhipuProvider` / `QwenProvider` 内部的 `httpx` 手写请求与 SSE 解析；对外方法、参数、异常传播不变。

### 不采用

| 候选 | 不采用理由 |
|---|---|
| `langchain-community` 的 `ChatZhipuAI` | 额外引入 `langchain-community` 与智谱 SDK，体积更大、版本耦合更强；现有端点本就 OpenAI 兼容 |
| LangChain `Chain` / `Runnable` 编排 | 4 个调用点彼此独立，无跨步骤编排收益；引入后反而扩大回归面 |
| LangChain Memory | 长期记忆是加密落库、可删除、可导出的自研数据模型；LangChain Memory 会绕开隐私链路 |
| LangChain Agent / Retriever | 本期无工具调用与检索需求 |
| 替换危机词库 / 合规过滤 | 二者是确定性规则，属安全红线，**不得**经过模型抽象 |

## 3. 依赖与版本锁定

### 直接依赖（写入 `backend/requirements.txt`，沿用 `==` 锁定风格）

```
langchain-openai==1.7.4
langchain-core==1.7.7
openai==2.54.0
```

- `openai` 必须 `<3`：3.x 默认引入 `httpx2` 运行时分支；2.54.0 复用现有 `httpx 0.28.1`。
- `langchain-openai 1.7.4` 要求 `langchain-core>=1.7.5,<2`、`openai>=2.45`、`tiktoken>=0.7`。

### 实测体积（不许估）

- 方法：在隔离 venv（Python 3.12 / macOS arm64）安装上述三个包，统计新增 site-packages 目录。
- 结果：新增 24 个包，**合计约 50.0 MB**（`openai` 19.3 MB、`langsmith` 9.4 MB、`langchain-core` 5.6 MB、`tiktoken` 3.0 MB、`zstandard` 2.0 MB、其余 ~10 MB）。
- Docker 镜像预计增长同量级（约 45–55 MB，Linux wheel 与 macOS wheel 略有差异）；镜像构建时 `--no-cache-dir` 不额外放大。
- 副作用：`langchain-core → langsmith` 会引入 `httpx2/httpcore2/truststore`，即**第二套 HTTP 客户端**。它只服务 tracing，本项目不开启 LangSmith；这是本次迁移最主要的非功能成本。

> **P0 止损门**：若评审认为 +50 MB 与第二套 HTTP 栈不可接受，可在 P0 后停止，不进入 P1；P0 不改变任何运行时行为。

## 4. 语义对齐矩阵

| 语义 | 迁移前 | 迁移后 | 验证方式 |
|---|---|---|---|
| 消息格式 | `list[dict]` 直接作 JSON body | `SystemMessage/HumanMessage/AIMessage` 转换后传入 | 新增单测：角色映射、空内容、未知角色降级为 `HumanMessage` |
| 温度 / 最大 token | 每次调用显式传参 | `client.bind(temperature=..., max_tokens=...)` | 单测断言绑定参数；业务测试沿用原参数 |
| 超时 | `httpx.Timeout(30, connect=10, write=10, pool=10)` | `ChatOpenAI(timeout=httpx.Timeout(30, connect=10))` | 单测断言构造参数 |
| 重试 | 调用层按 `max_attempts` 重试 | `ChatOpenAI(max_retries=0)`，重试仍由调用层负责 | `test_llm_fallback.py` 现有断言 `ZhipuProvider.max_attempts == 2` 不变 |
| 主备切换 | `FallbackProvider` | 不变 | 现有 `test_llm_fallback.py` 全量通过 |
| 流式增量 | 手写解析 `data:` 行，跳过空 delta | `astream()` → `chunk.content` 归一化为字符串，跳过空段 | 新增单测覆盖 `str` / `list[dict]` / 空 chunk |
| 首块前失败 | 抛异常，调用层重试 | 同左（`astream` 在首块前抛异常） | 现有流式重试用例 |
| 已产出后失败 | 抛异常 → `_StreamTruncated` | 同左 | 现有 `truncated` 用例 |
| 高危短路 | 不调用模型 | 不变 | `test_chat.py` 高危用例（fake provider 若被调用即抛错） |
| 合规过滤 | 输出侧规则 | 不变 | `test_compliance.py` |
| 心跳 / 断连落库 | 路由层 | 不变 | 现有 SSE 用例 |

**错误映射**：`ChatOpenAI` 抛出的 `openai.*Error` 在 provider 内统一包装为 `RuntimeError("模型调用失败：...")`，保持“任意 `Exception` 由调用层降级”的既有契约，并保留原始异常为 `__cause__`。

## 5. 测试替身改造

- **现有 33 处打桩不改**：类名与方法签名不变。
- 新增 `backend/tests/test_langchain_client.py`（约 6–8 例）：
  1. 角色映射；
  2. 未知角色降级；
  3. `chunk_text` 处理 `str`；
  4. `chunk_text` 处理 content block 列表；
  5. 空 chunk 返回空串；
  6. `build_client` 的 `base_url/timeout/max_retries` 断言（不发起网络）。
- 新增 `backend/tests/test_llm_boundary.py`（1 例）：扫描 `backend/app`，断言除 `app/llm/` 外无模块直接 `import langchain`，防止抽象泄漏。
- 预计用例总数：`1114 → 约 1122`，skip 仍为 1。

## 6. 分阶段实施

### P0 依赖与适配模块（行为零变化）

- 修改：`backend/requirements.txt`；新增 `backend/app/llm/langchain_client.py`；新增 `backend/tests/test_langchain_client.py`。
- 验证：`ruff check .`；`pytest -q`（基线 + 新增用例）；`python -c "import app.llm.langchain_client"`。
- 独立回滚：回退本提交即完全恢复，无运行时影响。

### P1 两个 provider 切换传输层

- 修改：`backend/app/llm/zhipu.py`、`backend/app/llm/qwen.py`（删除手写 `httpx` 与 SSE 解析，改用适配模块）；保留类名、构造参数、`max_attempts`、方法签名与 docstring 语义。
- 验证：`ruff check .`；`pytest -q` 必须仍是 `1114 passed, 1 skipped`（加 P0 新增用例后为预期总数）；重点跑 `test_llm_fallback.py`、`test_chat.py`、`test_emotion.py`、`test_long_memory.py`。
- 独立回滚：`git revert` 本提交即可恢复 HTTP 实现，P0 的依赖与测试保留不受影响。

### P2 文档、边界守卫与收口

- 修改：根 `README.md`（技术栈从“未使用 LangChain”改为实际依赖与体积说明）；`docs/README.md` 索引；新增 `backend/tests/test_llm_boundary.py`；本计划文档状态更新为“已实施”。
- 验证：`ruff check .`；`pytest -q`；`node --check` 不涉及；文档相对链接脚本校验。
- 独立回滚：仅文档与守卫，可单独回退。

## 7. 回滚方式

| 层级 | 操作 | 影响 |
|---|---|---|
| 代码级 | `git revert 7cafcd3` | 恢复手写 HTTP/SSE 实现，业务无感；P0 依赖与测试保留 |
| 依赖级 | `git revert 5872488` | 移除 LangChain 依赖，镜像回到基线 |
| 文档级 | `git revert 1ecc3ef` | 仅回退 README 与边界守卫，不影响运行 |
| 发布级 | 重新构建镜像并滚动重启 | 无数据迁移、无 schema 变更、无配置变更 |
| 数据级 | 无需回滚 | 本次不触碰数据库与加密字段 |

## 8. 风险与止损

| 风险 | 影响 | 缓解 |
|---|---|---|
| 镜像 +50 MB | 构建/拉取变慢 | P0 门评审；`--no-cache-dir`；不引入 `langchain` 元包 |
| 第二套 HTTP 栈（`httpx2`） | 依赖面扩大 | 不启用 LangSmith；边界测试禁止其他模块直接依赖 |
| 流式 chunk 结构差异（`str` vs content blocks） | 增量文本丢失 | `chunk_text` 归一化单测 + 现有流式用例 |
| 异常类型变化 | 降级分支失效 | provider 内统一包装为 `RuntimeError`，保留 `__cause__` |
| 隐式 SDK 重试叠加 | 调用次数放大 | `max_retries=0`，重试只保留调用层 |
| 测试替身失效 | 122 个用例回归 | 保留类名与方法签名，33 处打桩零改动 |
| 误把危机/合规链路纳入迁移 | 安全红线被改变 | 范围清单明确排除；边界测试与既有红线语料守护 |

**停止条件**：P1 后出现任一红线用例失败、流式截断/断连用例失败、或测试数低于基线，立即回滚 P1，不进入 P2。

## 9. 明确不做

- 不替换危机词库、合规规则、输出守卫。
- 不改 SSE 心跳、截断标记、断连落库。
- 不改会话/记忆的加密、导出、删除逻辑。
- 不引入 LangChain Memory / Chain / Agent / Retriever。
- 不改数据库 schema，不做数据迁移。

## 10. 真实端点验证（本地手工，2026-11-11）

CI 不带真实密钥，因此本节是**本地一次性人工验证**，不是自动化用例；密钥只存在于
`backend/.env`，未写入本文档、日志或提交。

**配置核实（仅列变量与形态，不含值）**：`ZHIPU_API_KEY` 存在且非占位（长度 49 字符）；
`ZHIPU_BASE_URL` 指向智谱 v4 开放平台；`MODEL_CHAT` 为 GLM 轻量档；`MODEL_LIGHT` 为
更轻的档位。`.env` 未配置 `QWEN_*`，通义备用通道未验证（`qwen_enabled` 默认关闭）。

**复现方式**：在 `backend/` 目录下，用项目配置（`get_settings()` 自动读取 `.env`）
直接构造 `ZhipuProvider` 并调用 `generate` / `stream`；再用 `build_client` 发起一次
`max_tokens=32` 的长文请求，读取响应的 `usage_metadata.output_tokens` 与
`response_metadata.finish_reason`。整个过程只打印耗时、字符数、token 数与文本摘要，
不打印任何密钥。

**观测结果**：

| 场景 | 观测值 | 结论 |
|---|---|---|
| 非流式 `generate` | 0.85s，返回 17 字 | 正常返回，无格式错误 |
| 流式 `stream` | 首块 0.38s，总 0.51s，10 个增量，18 字 | 增量按序到达，未混入空块 |
| `max_tokens=32` 长文请求 | `output_tokens=32`，`finish_reason=length` | 服务端接受 `max_tokens` 且按上限截断；若字段被改名为 `max_completion_tokens` 而遭忽略，输出不会被截断 |
| 无效 key | HTTP 401，包装为 `RuntimeError`，`__cause__` 为鉴权异常 | 错误映射符合调用层「任意异常→重试/降级」的契约 |

**结论**：GLM 主通道的请求形状、流式解析、长度上限与异常包装均与迁移前语义一致，
`max_tokens` 还原修复在真实服务端生效。

**遗留项**：

- DashScope 备用通道未做真实调用验证，首次启用备用时需补一次；
- `langsmith → httpx2` 作为第二套 HTTP 栈仍在依赖树中（不启用 LangSmith，由边界测试
  限制其使用范围）；
- 新增依赖实测 24 个包、约 50.0 MB，镜像同步增大约该量级。
