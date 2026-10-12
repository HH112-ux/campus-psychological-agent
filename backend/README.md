# 心屿 · 后端（FastAPI）

## 技术栈

Python 3.12 + FastAPI + Pydantic v2 + MongoDB（motor 异步驱动）+ 智谱 GLM。
本地开发依赖原生 MongoDB（`mongod`），部署用 `docker-compose`（见 `docker-compose.yml`）。

## 目录结构

```
backend/
├── app/
│   ├── main.py            # 应用入口（lifespan 连接 MongoDB）
│   ├── config.py          # 配置（.env 加载，pydantic-settings）
│   ├── core/              # 统一响应结构 + 业务异常 + 全局异常处理器
│   ├── db/                # motor 连接 + 集合/索引初始化
│   ├── llm/               # LLMProvider 抽象 + 智谱实现（预留通义适配位）
│   └── api/routes/        # 路由（当前：/health）
├── tests/                 # pytest
├── scripts/               # init_db / test_llm 等运维脚本
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

# 5. 启动服务
.venv/bin/uvicorn app.main:app --reload --port 8000
```

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

## 验证（P0 验收）

```bash
curl http://localhost:8000/health
# {"code":0,"message":"ok","data":{"status":"ok","service":"xinyu-backend",
#  "version":"0.1.0","env":"dev","db":"connected"}}

.venv/bin/python3.12 -m pytest -q     # 测试全绿
.venv/bin/ruff check .               # 静态检查无 error
.venv/bin/python3.12 -m scripts.test_llm # 智谱最简调用（需配置 ZHIPU_API_KEY，未配置时打印 SKIP）
```

交互式 API 文档：`http://localhost:8000/docs`（FastAPI 自动生成，与《API 文档》保持一致）。

## 注意事项

- `.env`、密钥文件严禁提交（已在 `.gitignore`）。
- 日志不记录对话原文与敏感字段（对齐 SECURITY.md）。
- 本仓库开发环境实测 MongoDB 8.0.4（官方 arm64 包）；开发文档标注 MongoDB 7，二者对本项目使用的 CRUD/索引无兼容差异。
