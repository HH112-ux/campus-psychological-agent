# 仓库治理规范：命名、文件格式与 Git/GitHub 同步规则

> 适用所有协作者。文档类一律使用 **Markdown（.md）**，不生成 HTML 文档；
> 提交与分支规范见 `CONTRIBUTING.md`，本文件补充文件级与仓库级规则。

## 一、命名规范

### 1. 目录与文件命名

| 对象 | 规则 | 示例 |
|---|---|---|
| 目录/文件 | `kebab-case`（小写 + 连字符），不用空格/下划线/驼峰 | `campus-agent-dev-doc/`、`crisis-lexicon-workflow.md` |
| Python 模块 | 全小写下划线（PEP 8） | `emotion_logs.py`、`risk_events.py` |
| Python 类 | 大驼峰 | `EmotionAnalyzer` |
| Python 函数/变量 | 全小写下划线 | `analyze_emotion()` |
| JS/小程序 | 小驼峰（变量/函数），页面目录小写 | `maybeShowConsent()`、`pages/logs/` |
| 环境/密钥文件 | 一律 `.env` 前缀，gitignore 兜底 | `backend/.env`、`.env.example` |
| 测试文件 | `test_<模块>.py` | `test_privacy.py` |
| 脚本（一次性/工具） | `backend/scripts/` 下 `kebab-case` 或 `<用途>_<阶段>.py` | `eval_emotion_p5.py` |
| 里程碑 Tag | `m<编号>`（里程碑）、`v<主>.<次>.<补丁>`（发布） | `m3`、`v0.3.0` |

### 2. 提交与分支命名

- 分支：`feature/<功能>` / `fix/<缺陷>` / `docs/<内容>`（见 CONTRIBUTING 分支模型）。
- Commit：`type(scope): 中文主题`，type ∈ `feat|fix|docs|refactor|test|chore|perf`。
- Tag：`m0`–`m5` 里程碑；发布 `v0.x.x`。

## 二、文件格式规范

1. **文档一律 Markdown**：`.md`，UTF-8，LF 行尾；不生成/不提交 HTML 文档。
   图表用 Mermaid（` ```mermaid `）或表格；图片引用仓库内相对路径。
2. **代码格式**：
   - Python：ruff（select E,F,W,I,UP，line-length 110），`pytest` 为测试入口；
   - JS：2 空格缩进，`node --check` 做语法门；
   - 所有文本文件 UTF-8 + LF + 末尾换行（`.editorconfig` + `.gitattributes` 强制）。
3. **配置模板**：需要提交的环境样例用 `.env.example`，真实密钥只放本地 `.env`。

## 三、什么入库 / 什么不入库（Git 与 GitHub 上传规则）

### 必须入库
- 源码、测试、接口/开发文档（.md）、评估脚本与数据、配置模板、本规范文件。

### 严禁入库（gitignore 已覆盖，双保险）
- 密钥与凭据：`.env`、`*.pem`、`*.key`、`secrets/`、token/PAT（见 SECURITY.md）；
- 本地环境：`.venv/`、`.venv39/`、`__pycache__/`、`node_modules/`；
- 缓存/日志：`.pytest_cache/`、`.ruff_cache/`、`*.log`、`tmp/`；
- 系统文件：`.DS_Store`、`~$*`（Office 锁文件）；
- 本地文档：`*.docx` / `*.doc` / `*.pdf`（报告等留本地，不入库）；
- 工具生成：`.trae-html-share-packages/`、`{{pkgetc}}/`；
- 小程序私有配置：`project.private.config.json`。

### 上传前检查（Push Checklist）
1. `git status` 确认无 `??` 中的敏感/临时文件；
2. `git ls-files | grep -E "\.env$|\.key|\.pem|\.log|~$"` 应为空；
3. 后端改动用 `ruff check .` + `pytest -q` 全绿；
4. 前端改动用 `node --check` 通过；
5. Commit 消息符合 CONTRIBUTING 规范；Tag 只在里程碑验收后打；
6. 推送用 `git push`（PAT 仅授权环境使用，不写入 remote 配置）。

## 四、项目结构（预期布局）

```
campus-psychological-agent/
├── backend/            # FastAPI 后端
│   ├── app/            # 应用代码（api/ routes 层 → services 层 → db 层）
│   │   ├── api/routes/ # 路由层：只编排，不直接操作集合
│   │   ├── services/   # 业务层：持久化统一入口
│   │   ├── core/       # 通用（依赖/异常/响应/加密）
│   │   ├── db/         # Mongo 连接与索引
│   │   ├── models/     # Pydantic 模型
│   │   ├── llm/        # 模型 Provider
│   │   └── main.py
│   ├── scripts/        # 一次性/评估/压测脚本
│   ├── tests/          # pytest
│   └── requirements.txt
├── miniprogram/        # 微信小程序原生工程
├── docs/               # 工程规范与阶段留档（全部 .md）
├── campus-agent-dev-doc/   # 开发文档（.md 为准）
├── campus-agent-api-doc/   # API 文档（.md 为准；内容已并入 README）
├── .github/            # GitHub 模板（PR/Issue）
├── README.md / CONTRIBUTING.md / SECURITY.md / CHANGELOG.md
└── .gitignore / .gitattributes / .editorconfig
```

## 五、GitHub 协作规则（通用实践）

- PR 模板（`.github/PULL_REQUEST_TEMPLATE.md`）与 Issue 模板（`.github/ISSUE_TEMPLATE/`）已提供；
- main 分支受保护：合入前 `pytest` + `ruff` 全绿（质量门见 CONTRIBUTING 第 5 节）；
- 敏感信息（PAT、密钥）永不进 Issue/PR/Commit；发现泄露立即吊销并轮换；
- 文档改动与代码改动分开提交，方便评审与回溯。
