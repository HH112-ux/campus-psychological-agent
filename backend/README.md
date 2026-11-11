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
├── requirements.txt       # 生产依赖（Docker 只装这一份）
└── requirements-dev.txt   # 测试与 lint（pytest / ruff），本地与 CI 安装
```

## 本地启动

```bash
# 1. 环境变量
cp .env.example .env          # 填写 ZHIPU_API_KEY 等
# 模板默认面向部署（ENV=prod、WX_MOCK_LOGIN=false）。本地纯开发：
#   ENV=dev、WX_MOCK_LOGIN=true，否则会因缺少生产凭据直接拒绝启动

# 2. MongoDB（两种方式任选）
#    方式 A：本机原生 mongod（见项目根 README 的 MongoDB 安装说明）
#    方式 B：docker compose up -d mongo

# 3. Python 虚拟环境（Python 3.12）
python3.12 -m venv .venv
.venv/bin/python3.12 -m pip install -r requirements.txt -r requirements-dev.txt
# 生产镜像只安装 requirements.txt；requirements-dev.txt 仅供本地/CI 测试与 lint

# 4. 初始化数据库（集合 + 索引）
.venv/bin/python3.12 -m scripts.init_db

# 5. 播种危机词库与求助资源（幂等，重复执行只 upsert）
.venv/bin/python3.12 -m scripts.seed_crisis

# 6. 启动服务
.venv/bin/uvicorn app.main:app --reload --port 8000
```

> **历史数据加密迁移（B1）**：`emotion_records.evidence`、`messages.emotion.evidence`、
> `checkins.note`、`risk_events.matched` 已改为与对话正文一致的 AES-256-GCM 存储。
> 已有数据升级后先 dry-run 再执行（幂等，可重复跑；必须配置 `DATA_ENCRYPTION_KEY`）：
>
> ```bash
> .venv/bin/python3.12 -m scripts.migrate_encrypt_sensitive_fields --dry-run
> .venv/bin/python3.12 -m scripts.migrate_encrypt_sensitive_fields
> ```
>
> **MongoDB 访问**：生产 compose 已开启 `--auth`，且不再向宿主机发布 `27017`；
> `api` 容器通过 `MONGODB_URI`（带凭据，host 用 `mongo`）访问。需要本机调试时用
> `docker compose exec mongo mongosh -u "$MONGO_ROOT_USERNAME" -p`，不要恢复端口映射。

> V1 双周复盘：`.venv/bin/python scripts/export_bad_cases.py --days 14 --out /tmp/bad-cases.json`
> 导出点踩 bad-case（含解密对话内容，产物已 gitignore，**严禁入库**），
> 按 `docs/bad-case-review-template.md` 归类复盘。

### 微信登录配置（P1）

真机登录需在小程序后台获取 `WX_SECRET`；本地无 Secret 时用 mock 模式（`.env`）：

```bash
ENV=dev                    # 非 dev 环境一律拒绝 mock 登录（启动即失败）
WX_APPID=wx641b560961211693
WX_SECRET=                 # 本地留空
WX_MOCK_LOGIN=true         # 本地 true：用固定 mock openid 模拟 code2session；真机/部署置 false
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

## 部署（docker-compose，HTTPS）

生产用 `prod` profile 启动 api / mongo / nginx；nginx 同时监听 80 与 443，
**80 只做 301 跳转到 HTTPS**（`/health` 例外，供编排探活），全链路不提供明文业务入口。

```bash
cd backend
cp .env.example .env                       # 填写密钥、Mongo 凭据、TLS_SERVER_NAME
mkdir -p nginx/certs                       # 放入 server.crt / server.key（严禁入库）
docker compose --profile prod up -d --build
```

- 证书路径可用 `TLS_CERT_PATH` / `TLS_KEY_PATH` 覆盖，默认 `/etc/nginx/certs/server.crt|key`；
  容器启动时由 `nginx/docker-entrypoint.sh` 渲染模板并执行 `nginx -t`；
- 证书或私钥缺失、为空、与私钥不匹配时，nginx 容器**启动即失败**并打印
  `[xinyu-nginx] 启动失败：…`，不会静默降级为明文 HTTP；
- 备案域名就绪后把 `TLS_SERVER_NAME` 设为该域名，并在小程序后台配置 request 合法域名；
- 证书过期前替换 `backend/nginx/certs/` 内文件后 `docker compose --profile prod restart nginx`。

## 验证

```bash
curl http://localhost:8000/health
# {"code":0,"message":"ok","data":{"status":"ok","service":"xinyu-backend",
#  "version":"0.1.0","env":"dev","db":"connected"}}

.venv/bin/python3.12 -m pytest -q     # 1128 passed, 1 skipped（共 1129 项；skip：真 Redis 集成，按需设置 REDIS_TEST_URL）
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
