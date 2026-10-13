# 心屿 · 后端（FastAPI）

## 技术栈

Python 3.12 + FastAPI + Pydantic v2 + MongoDB（motor 异步驱动）+ 智谱 GLM。
本地开发依赖原生 MongoDB（`mongod`），部署用 `docker-compose`（见 `docker-compose.yml`）。

## 目录结构

```
backend/
├── app/
│   ├── main.py            # 应用入口（lifespan 连接 MongoDB，注册全部路由）
│   ├── config.py          # 配置（.env 加载，pydantic-settings）
│   ├── core/              # 统一响应/异常、JWT 安全、依赖注入、内存限流、时间工具
│   ├── db/                # motor 连接 + 集合/索引初始化 + ObjectId 解析
│   ├── llm/               # LLMProvider 抽象 + 智谱实现（含 SSE 流式与超时）
│   ├── models/            # pydantic 请求模型（auth/session/message）
│   ├── services/          # 微信登录、用户、会话、危机检测、提示词、记忆、对话编排
│   └── api/routes/        # auth/users/sessions/messages/crisis + /health
├── tests/                 # pytest（危机红线 + 认证/会话/消息集成）
├── scripts/               # init_db / seed_crisis / test_llm 等运维脚本
├── docker-compose.yml     # 部署编排（api/mongo/nginx）
├── .env.example           # 环境变量模板（复制为 .env 填写）
└── requirements.txt
```

## 本地启动

```bash
# 1. 环境变量
cp .env.example .env          # 填写 ZHIPU_API_KEY 等

# 2. MongoDB（两种方式任选）
#    方式 A：本机原生 mongod（见项目根 README 的 MongoDB 安装说明）
#    方式 B：docker compose up -d mongo

# 3. Python 虚拟环境（Python 3.12）
python3.12 -m venv .venv
.venv/bin/python3.12 -m pip install -r requirements.txt

# 4. 初始化数据库（集合 + 索引）
.venv/bin/python3.12 -m scripts.init_db

# 5. 播种危机词库与求助资源（幂等，重复执行只 upsert）
.venv/bin/python3.12 -m scripts.seed_crisis

# 6. 启动服务
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### 微信登录配置（P1）

真机登录需在小程序后台获取 `WX_SECRET`；本地无 Secret 时用 mock 模式（`.env`）：

```bash
WX_APPID=wx641b560961211693
WX_SECRET=                 # 本地留空
WX_MOCK_LOGIN=true         # 本地 true：用固定 mock openid 模拟 code2session；真机置 false
WX_MOCK_OPENID=mock_dev_openid
```

> 危机拦截为本地词库同步判定，不依赖大模型；即使智谱 Key 不可用，高危句仍会 100% 命中危机卡片。

> 本机 Python 3.12 为免 sudo 安装在 `~/Library/Frameworks`（非系统 `/Library/Frameworks`），
> 运行 venv 内任何命令前需先导出动态库路径（每个新终端都要执行一次）：
>
> ```bash
> export DYLD_FRAMEWORK_PATH="$HOME/Library/Frameworks"
> export DYLD_LIBRARY_PATH="$HOME/Library/Frameworks/Python.framework/Versions/3.12/lib"
> ```
>
> 也可直接使用封装好的解释器 `~/bin/python3.12`（已内置上述变量）。
> 统一用 `.venv/bin/python3.12` 调用，避免裸 `python` 命中系统其他版本。

## 验证

```bash
curl http://localhost:8000/health
# {"code":0,"message":"ok","data":{"status":"ok","service":"xinyu-backend",
#  "version":"0.1.0","env":"dev","db":"connected"}}

.venv/bin/python3.12 -m pytest -q     # 46 项全绿（危机红线 + 认证/会话/消息 + P0）
.venv/bin/ruff check .               # 静态检查无 error
.venv/bin/python3.12 -m scripts.test_llm # 智谱最简调用（需配置 ZHIPU_API_KEY，未配置时打印 SKIP）
```

- 集成测试使用独立测试库 `xinyu_test`（与开发库 `xinyu` 隔离，需本地 MongoDB 在 27017）；未启动 MongoDB 时自动跳过集成测试，危机红线纯逻辑测试仍会运行。
- 危机红线测试见 `tests/test_crisis.py`：高危句（含空格/标点/拼音/谐音变体）必须 100% 判 high，正常句不得误报，是安全红线的自动化保障。

### 手工验证 P1 链路

```bash
# 1. mock 登录拿 token
curl -s -X POST http://localhost:8000/api/v1/auth/wx-login \
  -H "Content-Type: application/json" -d '{"code":"any"}'
# 2. 用返回的 access_token 建会话、发消息（stream:true 看 SSE 帧）
# 3. 发"我不想活了"应直接返回危机话术与求助资源，不调用大模型
```

交互式 API 文档：`http://localhost:8000/docs`（FastAPI 自动生成，与《API 文档》保持一致）。

## 注意事项

- `.env`、密钥文件严禁提交（已在 `.gitignore`）。
- 日志不记录对话原文与敏感字段（对齐 SECURITY.md）。
- 本仓库开发环境实测 MongoDB 8.0.4（官方 arm64 包）；开发文档标注 MongoDB 7，二者对本项目使用的 CRUD/索引无兼容差异。
