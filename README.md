# 心屿 · 校园心理咨询智能陪伴 Agent

面向高校学生的微信小程序：随时与 AI 陪伴者「小屿」多轮对话倾诉，系统识别焦虑、抑郁等情绪并给出疏导建议，长期沉淀为情绪日志；识别到持续低落或危机信号时，主动递上专业求助资源。

> **定位**：倾诉出口 + 自我觉察 + 专业资源的桥。**不输出诊断结论、不推荐药物、不宣称治疗作用、不替代专业心理咨询。**

## 功能范围

- **对话陪伴**：SSE 流式回复，不支持分块时自动降级为普通响应；会话标题、历史消息可回看。
- **情绪识别与日志**：每轮识别情绪类型，支持每日五档打卡（平静 / 还行 / 低落 / 焦虑 / 烦躁）与情绪记录。
- **危机识别与转介**：本地危机词库（不依赖大模型）识别高危表达，命中即返回内置求助资源并记录风险事件。
- **长期记忆**：跨会话记住人物、事件、偏好与情绪诱因，可在「我的」页查看、单条删除或清空。
- **练习卡片**：呼吸、正念、行为激活三类可交互练习，完成记录留档。
- **语音输入**：录音 → 转写 → 用户确认后发送；音频转写后即弃，不落库、不落盘。
- **隐私与数据权利**：服务端强制隐私同意、对话与记忆加密存储、数据导出、到期物理删除。

**明确不做**：医疗诊断、用药建议、疗效承诺、危机现场处置（仅转介）。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · Pydantic v2 · motor（MongoDB 异步驱动） |
| 数据 | MongoDB 7（业务数据）· Redis（限流与跨实例计数，可选，Redis 不可达时降级进程内） |
| 模型 | 智谱 GLM（主模型 + 轻量档），可选通义千问作为备用供应商（默认关闭） |
| 小程序 | 微信小程序原生 WXML / WXSS / JavaScript |
| 部署 | Docker Compose（`api` + `mongo` + `nginx`，`prod` profile） |

> 模型调用对外仍是自封装的 `LLMProvider` 抽象（`backend/app/llm/`），传输层使用
> `langchain-openai` 的 `ChatOpenAI`。只替换 HTTP/SSE 传输，**不引入** LangChain 的
> chain / memory / agent；危机判定、合规过滤、长期记忆与 SSE 协议均不依赖 LangChain。
> 该依赖使镜像增加约 50 MB（实测 24 个包），并带入 `httpx2` 作为 LangSmith 的传递依赖
> （本项目不启用 LangSmith）。

## 目录结构

```
campus-psychological-agent/
├── backend/                    # FastAPI 后端（Python 3.12）
│   ├── app/
│   │   ├── api/routes/         # auth / users / sessions / messages / emotion / crisis / practices / speech / memory / health
│   │   ├── core/               # 统一响应与异常、JWT、依赖注入、限流、加密、时间与指标
│   │   ├── db/                 # motor 连接、集合与索引初始化、用户数据登记表
│   │   ├── llm/                # LLMProvider 抽象 + 智谱/通义实现 + 路由与降级
│   │   ├── models/             # Pydantic 请求模型
│   │   └── services/           # 登录、会话、危机、合规、记忆、练习、语音、隐私等
│   ├── scripts/                # init_db / seed_crisis / 历史数据迁移 / 评估脚本
│   ├── tests/                  # pytest（红线语料 + 接口集成）
│   ├── nginx/                  # 反向代理模板与证书挂载点
│   ├── docker-compose.yml      # mongo / nginx / api（prod profile）
│   ├── Dockerfile
│   ├── requirements.txt        # 生产依赖（镜像只装这一份）
│   └── requirements-dev.txt    # pytest / ruff（本地与 CI）
├── miniprogram/                # 微信小程序原生工程
│   ├── config.js               # 发布地址唯一入口（按 envVersion 选择 develop/trial/release）
│   ├── pages/                  # index / chat / sessions / memories / practice / logs / mine
│   ├── components/             # crisis-card 等
│   ├── utils/                  # api.js（登录/刷新/统一请求）· sse.js
│   └── project.config.json     # urlCheck: true（域名校验默认开启）
├── docs/                       # 设计规范、开发测试、部署运维、合规、危机与历史审查（索引见 docs/README.md）
├── campus-agent-dev-doc/       # 开发文档（Markdown 为准）
├── campus-agent-api-doc/       # API 契约（Markdown 为准）
├── tools/                      # 图标生成等辅助脚本
└── .github/                    # CI 工作流与 PR / Issue 模板
```

## 本地快速启动

前置：Python 3.12、MongoDB 7；小程序调试需微信开发者工具；仅跑 JS 语法检查需 Node.js 20。

### 后端

```bash
cd backend

# 1. 环境变量（.env 不入库）
cp .env.example .env
# 模板默认面向部署（ENV=prod、WX_MOCK_LOGIN=false）；
# 本地开发请改为 ENV=dev、WX_MOCK_LOGIN=true，并填写 ZHIPU_API_KEY

# 2. 依赖
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# 3. MongoDB（任选其一）
docker compose up -d mongo      # 或使用本机 mongod

# 4. 初始化集合与索引，播种危机词库与求助资源（幂等）
.venv/bin/python3.12 -m scripts.init_db
.venv/bin/python3.12 -m scripts.seed_crisis

# 5. 启动
.venv/bin/uvicorn app.main:app --reload --port 8000

# 6. 健康检查
curl http://localhost:8000/health
# {"code":0,"message":"ok","data":{"status":"ok","service":"xinyu-backend","version":"0.1.0","env":"dev","db":"connected"}}
```

更多说明见 [backend/README.md](backend/README.md)。

### 小程序

1. 微信开发者工具选择「导入项目」，目录指向 `miniprogram/`，AppID 填 `wx641b560961211693`，后端选「不使用云服务」。
2. 先按上文启动后端（默认 `127.0.0.1:8000`）。`miniprogram/project.config.json` 已开启域名校验（`urlCheck: true`）；本地连 `127.0.0.1` 时，在「详情 → 本地设置」勾选「不校验合法域名…」即可，该开关只写入已被 gitignore 的 `project.private.config.json`。
3. 真机预览需让手机与电脑同网，并把 `miniprogram/config.js` 的 `API_BASE.develop` 改为电脑局域网 IP。
4. 提审前在 `config.js` 的 `API_BASE.trial` / `API_BASE.release` 填入已备案的 HTTPS 域名，并在微信后台配置合法域名。

更多说明见 [miniprogram/README.md](miniprogram/README.md)。

## 测试与质量门

```bash
# 后端：静态检查 + 全量测试
cd backend
.venv/bin/ruff check .
.venv/bin/pytest -q
# 当前基线：1138 passed, 1 skipped（共 1139 项）
# 唯一 skip：tests/test_ratelimit_redis.py 的真 Redis 集成用例，设置 REDIS_TEST_URL 后启用

# 小程序：JS 语法检查 + 单元测试
find miniprogram -name '*.js' -print0 | xargs -0 -n1 node --check
node --test miniprogram/tests/*.test.js
```

CI 见 [.github/workflows/ci.yml](.github/workflows/ci.yml)：`ruff + pytest`、`node --check`、情绪与长期记忆评估回归门（未配置 `ZHIPU_API_KEY` 时评估 job 打印 SKIP 并以 0 退出，不代表评估达标）。评估口径见 [docs/eval-gate.md](docs/eval-gate.md)。

## 部署入口

```bash
cd backend
# 先准备 .env：ENV=prod、WX_MOCK_LOGIN=false、WX_SECRET、JWT_SECRET、MONGO_ROOT_* 等
docker compose --profile prod up -d --build
```

- 上线步骤与检查项：[docs/miniprogram-go-live-checklist.md](docs/miniprogram-go-live-checklist.md)
- 本机生产编排演练记录：[docs/prod-deploy-drill-2026-11-10.md](docs/prod-deploy-drill-2026-11-10.md)
- 证书、镜像源、Nginx 与持久化说明：[backend/README.md](backend/README.md)（`backend/nginx/` 为证书挂载点）

## 文档索引

完整文档分类见 [docs/README.md](docs/README.md)。常用入口：

| 文档 | 用途 |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发流程、提交规范与验收要求 |
| [SECURITY.md](SECURITY.md) | 漏洞报告、密钥与数据保护策略 |
| [docs/repo-governance.md](docs/repo-governance.md) | 命名、文件格式与入库规则 |
| [docs/privacy-policy.md](docs/privacy-policy.md) | 隐私政策（数据处理与用户权利） |
| [docs/crisis-response-sop.md](docs/crisis-response-sop.md) | 高危事件人工响应 SOP |
| [docs/crisis-lexicon-workflow.md](docs/crisis-lexicon-workflow.md) | 危机词库变更流程 |
| [campus-agent-api-doc/campus-agent-api-doc.md](campus-agent-api-doc/campus-agent-api-doc.md) | API 契约 |
| [campus-agent-dev-doc/campus-agent-dev-doc.md](campus-agent-dev-doc/campus-agent-dev-doc.md) | 需求、架构与验收标准 |

## 许可与免责声明

- **许可**：本项目为校内项目，**保留所有权利**（未声明开源许可，暂不提供 `LICENSE`）；如需引用或复用，请先联系维护者。
- **免责**：本产品为校园心理陪伴工具，**不是医疗器械**，不提供诊断、治疗或用药建议，不能替代专业心理咨询与精神科诊疗。
- **紧急情况**：如存在立即的人身危险，请直接拨打 `120` / `110`，或联系当地心理援助热线与学校心理中心。
- **数据**：数据处理与用户权利以 [docs/privacy-policy.md](docs/privacy-policy.md) 为准；安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
