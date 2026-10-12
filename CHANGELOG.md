# 变更日志

本文件记录「心屿」项目的所有重要变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循[语义化版本](docs/versioning.md)。

## [Unreleased]

### 新增

- 仓库基线：开发文档、API 文档、贡献规范（CONTRIBUTING）入库，建立 main 分支与 m0 里程碑。
- 任务拆分规范：按 F1–F6 功能编号拆分任务，关联阶段与 API 接口（docs/task-management.md）。
- 版本与发布策略：SemVer + m/v 双 tag 规则（docs/versioning.md）。
- 危机词库变更流程：五步闭环 + 回滚 + 误报反馈闭环（docs/crisis-lexicon-workflow.md）。
- 安全策略：漏洞报告、密钥管理、依赖安全、数据保护与应急响应（SECURITY.md）。
- P0 后端脚手架：FastAPI 应用入口、统一响应/异常、配置中心（pydantic-settings）、motor 连接与 8 个集合索引、智谱 LLM Provider（含 SSE 流式）、`/health` 路由、init_db/test_llm 脚本、pytest 与 ruff 配置、Dockerfile 与 docker-compose。
- P0 小程序占位工程：原生框架可编译启动，占位首页含 `/health` 连通性检测。
- P0 验收：`GET /health` 返回 200 且 `db: connected`，pytest 3 项全绿，ruff 无 error；智谱真实调用待配置 API Key。
