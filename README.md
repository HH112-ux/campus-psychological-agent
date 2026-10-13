# 心屿 · 校园心理咨询智能陪伴 Agent

面向高校学生的微信小程序：随时与 AI 陪伴者「小屿」多轮对话倾诉，系统识别焦虑、抑郁等情绪并给出疏导建议，长期沉淀为情绪日志；识别到持续低落或危机信号时，主动递上专业求助资源。

> 定位：倾诉出口 + 自我觉察 + 专业资源的桥。**不输出诊断结论、不推荐药物、不宣称治疗作用。**

## 仓库结构

```
campus-psychological-agent/
├── backend/               # FastAPI 后端（P0 起逐步搭建）
├── miniprogram/           # 微信小程序原生工程（P0 起逐步搭建）
├── docs/                  # 工程规范：任务拆分 / 版本策略 / 危机词库变更流程
│   ├── task-management.md
│   ├── versioning.md
│   └── crisis-lexicon-workflow.md
├── campus-agent-dev-doc/  # 开发文档（交互原型 + 功能需求 + 技术方案）
├── campus-agent-api-doc/  # API 文档（接口契约）
├── CONTRIBUTING.md        # 开发流程与提交规范（必读）
├── SECURITY.md            # 安全策略（漏洞报告 / 密钥 / 数据保护）
├── CHANGELOG.md           # 变更日志
└── .gitmessage            # git commit 消息模板
```

## 技术栈（立项固定）

FastAPI + LangChain + 智谱 GLM（主模型 + 轻量档）+ 微信小程序原生 + MongoDB，部署为 docker-compose（FastAPI + MongoDB + Nginx）。

## 开发流程速览（8 周 5 阶段）

| 阶段 | 内容 | 时点 |
|---|---|---|
| P0 | 环境与基建（AppID / FastAPI 脚手架 / MongoDB / 智谱 Key） | 第 1 周 |
| P1 | 对话闭环 + 最小危机词库（红线，不依赖模型） | 第 2–3 周 |
| P2 | 小程序完整页面 | 第 4 周 |
| P3 | 情绪识别与日志 | 第 5 周 |
| P4 | 危机干预与合规加固（红线） | 第 6 周 |
| P5 | 评估、内测与提审（红线） | 第 7–8 周 |

完整需求、验收标准与里程碑见 `campus-agent-dev-doc/`，接口契约见 `campus-agent-api-doc/`。

## 快速开始

1. 阅读 `CONTRIBUTING.md`，按提交规范开发。
2. 后端：见 `backend/README.md`（venv → init_db → seed_crisis 播种危机词库 → uvicorn，验收 `GET /health` 返回 200 且 `db: connected`，pytest 46 项全绿）。
3. 小程序：见 `miniprogram/README.md`（微信开发者工具导入 `miniprogram/`，P1 已具备会话列表、流式对话页与危机求助卡片；本地无 `WX_SECRET` 时后端走 mock 登录）。
4. 按阶段文档推进，每个阶段验收通过后打里程碑 tag（见 CONTRIBUTING）。
5. 密钥一律放 `.env`（不入库），参考 `backend/.env.example`。

## 安全红线（验收一票否决）

- 危机词库最小版在 P1 必须可用，危机信号召回 ≥ 95%，宁可误报不可漏报。
- 对话内容加密存储；敏感信息不进日志；所有查询强制按 user_id 隔离。
- 高风险信号只做转介（求助卡片），产品自身不处理危机。
