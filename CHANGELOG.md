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
- P0 验收：`GET /health` 返回 200 且 `db: connected`，pytest 3 项全绿，ruff 无 error；智谱 `glm-4-air`（主对话）/ `glm-4-flash`（轻量）双档位真实调用均已实测返回。
- P1 认证：微信 `wx.login` → `code2session` 换 openid（支持真机与本地 `WX_MOCK_LOGIN` 双模式）、JWT 双令牌（access 7 天 / refresh 30 天）、refresh 旋转即旧 token 作废、`/users/me`；openid 只存服务端，不写入令牌也不下发。
- P1 会话：列表/创建/详情/重命名/删除，强制 `user_id` 隔离（跨用户统一 404，不暴露存在性）；单用户活跃会话上限 3、单会话轮次上限 50、首条消息前 12 字自动回填标题。
- P1 对话（MVP 核心）：非流式与 SSE 流式（`meta → delta → crisis → done / error` 帧）、提示词 V1（共情陪伴 + 单次 ≤120 字）、近 20 轮窗口记忆、模型超时/异常重试 1 次后降级为固定话术；流式按块间隔判超时。
- P1 危机红线：本地两级词库同步拦截器（不依赖模型），内置 55 条一级强信号（命中即 high，不调大模型，直接固定危机话术）+ 33 条二级语境词（每命中一个不同词 +2、会话累计 ≥4 升 high）；覆盖空格/标点/符号、拼音与网络谐音等基础变体；高危卡片置顶常驻、mid 卡片流后插入，4 条求助热线并支持一键拨打；所有 mid/high 写 `risk_events`（仅记命中词与 lexicon 来源，不存原文），会话删除后风险事件仍留存审计。
- P1 反馈：助手回复点赞 / 点踩（点踩必须选择原因）。
- P1 限流：内存固定窗口单机内测（登录 10 次/分/IP、消息 30 条/时/用户、读 60 次/分/用户），代码注释标注生产需替换为 Nginx/Redis。
- P1 小程序：静默登录封装（自动携带 JWT、401 静默刷新并自动重放）；SSE 流式对话页（`enableChunked` + 跨 chunk 安全 UTF-8 解码、按 `\n\n` 断帧、10s 无增量中断、旧基础库自动降级非流式）；高危卡片置顶常驻 / mid 卡片插入流、一键拨打热线；会话列表（新建/进入/重命名/删除）；高危卡片在重进会话时依据 `crisis_high_shown` 恢复。
- P1 测试：后端 46 项 pytest 全绿（28 项危机红线用例含 18 个高危变体与 6 个防误报、15 项 P1 认证/会话/消息集成测试 mock LLM、3 项 P0），ruff 无 error；小程序 SSE 解码经 Node 模拟逐字节/分块/大块三种切分验证通过。

