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

> **命名豁免清单**：以下为工具/构建产物目录，**不受 kebab-case 约束**，且一律不入库（见第三节）：`_shared/`、`{{pkgetc}}/`、`.trae-html-share-packages/`、`node_modules/`、`miniprogram_npm/`。
> 其余目录一律 kebab-case（含数据目录，如 `backend/scripts/eval-data/`）；Python 模块例外（下划线，见上表）。

### 2. 提交与分支命名

- 分支：`feature/<功能>` / `fix/<缺陷>` / `docs/<内容>`（见 CONTRIBUTING 分支模型）。
- Commit：`type(scope): 中文主题`，type ∈ `feat|fix|docs|refactor|test|chore|perf`。
- Tag：`m0`–`m5` 里程碑；发布 `v0.x.x`。

## 二、文件格式规范

1. **文档一律 Markdown**：`.md`，UTF-8，LF 行尾；**不生成、不提交 HTML 文档**。
   图表用 Mermaid（` ```mermaid `）或表格；独立图源可存 `.mmd`（如 `docs/architecture-dependency.mmd`）；图片引用仓库内相对路径。
   **执行方式**：`campus-agent-*-doc/` 下若生成 HTML 预览包（`*.html` + `_shared/` 字体与 JS + `assets/`），一律不入库，由 `.gitignore` 拦截；**`.md` 为唯一入库来源**。
2. **代码格式**：
   - Python：ruff（select E,F,W,I,UP，line-length 110），`pytest` 为测试入口；
   - JS：2 空格缩进，`node --check` 做语法门；
   - 所有文本文件 UTF-8 + LF + 末尾换行（`.editorconfig` + `.gitattributes` 强制）。
3. **配置模板**：需要提交的环境样例用 `.env.example`，真实密钥只放本地 `.env`。

## 三、什么入库 / 什么不入库（Git 与 GitHub 上传规则）

### 必须入库
- 源码、测试、接口/开发文档（.md）、评估脚本与数据、配置模板、本规范文件。
- GitHub 协作资产：`.github/workflows/`（CI）、`PULL_REQUEST_TEMPLATE.md`、`ISSUE_TEMPLATE/`。

### 严禁入库（gitignore 已覆盖，双保险）
- 密钥与凭据：`.env`、`*.pem`、`*.key`、`secrets/`、token/PAT（见 SECURITY.md）；
- 本地环境：`.venv/`、`.venv39/`、`__pycache__/`、`node_modules/`；
- 缓存/日志：`.pytest_cache/`、`.ruff_cache/`、`*.log`、`tmp/`；
- 系统文件：`.DS_Store`、`~$*`（Office 锁文件）；
- 本地文档：`*.docx` / `*.doc` / `*.pdf`（报告等留本地，不入库；**不得散落在根目录**，应放仓库外）；
- 工具生成：`.trae-html-share-packages/`、`{{pkgetc}}/`；
- HTML 文档产物：`campus-agent-*-doc/*.html`、`_shared/`、`assets/`（文档以 `.md` 为准）；
- 游离配置：仓库根目录不得出现 `project.config.json`（真身在 `miniprogram/`）；
- 小程序私有配置：`project.private.config.json`。

### 上传前检查（Push Checklist）
0. **根目录清洁**：根目录只含项目级文件（源码目录、顶层 `*.md`、点号配置、`docker-compose` 等）；本地文档与游离配置不得出现；
1. `git status` 确认无 `??` 中的敏感/临时文件；
2. **敏感与产物复查**：`git ls-files | grep -E "\.env$|\.key$|\.pem$|\.log$|~$|\.html$|\.ttf$"` 应为空（HTML 文档包与字体不入库）；
3. 后端改动：`ruff check .` + `pytest -q` 全绿（与 CI 同一门槛，**CI 绿后再合入 `main`**）；
4. 前端改动：`node --check` 通过；
5. Commit 消息符合 CONTRIBUTING 规范；Tag 只在里程碑验收后打；
6. 推送用 `git push`（PAT 仅授权环境使用，不写入 remote 配置，**切勿把 PAT 贴入对话 / Issue / PR**）。

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
├── campus-agent-dev-doc/   # 开发文档（.md 为准；HTML 预览包与 _shared/ 不入库）
├── campus-agent-api-doc/   # API 文档（.md 为准；内容已并入 README）
├── .github/            # GitHub 模板（PR/Issue）+ CI 工作流（workflows/）
├── README.md / CONTRIBUTING.md / SECURITY.md / CHANGELOG.md
└── .gitignore / .gitattributes / .editorconfig
```

## 五、GitHub 协作规则（通用实践）

- PR 模板（`.github/PULL_REQUEST_TEMPLATE.md`）与 Issue 模板（`.github/ISSUE_TEMPLATE/`）已提供；
- main 分支受保护：合入前 **CI 必须全绿**（`ruff` + `pytest` + `node --check`，见第六节与 CONTRIBUTING 第 5 节）；
- 敏感信息（PAT、密钥）永不进 Issue/PR/Commit；发现泄露立即吊销并轮换；
- 文档改动与代码改动分开提交，方便评审与回溯。

## 六、CI 与质量门（GitHub Actions）

工作流：`.github/workflows/ci.yml`，在 push / PR 到 `main` 时触发。

| Job | 检查项 | 本地等价命令 |
|---|---|---|
| backend | 依赖安装 → `ruff check .` → `pytest -q`（含 MongoDB 服务容器） | `ruff check .` + `pytest -q` |
| miniprogram | 全量 JS 语法门 | `find miniprogram -name '*.js' -exec node --check {} +` |

- **合入 `main` 前 CI 必须为绿**；本地可在功能分支上先跑同一门槛再提 PR。
- CI 与本地使用同一配置（`backend/pyproject.toml` 的 ruff/pytest 规则），不允许「本地过、CI 不过」的口径差。
- 许可：本仓库**未声明开源许可**，在维护者决定前一律视为「保留所有权利」；若要开源，先补 `LICENSE` 再对外宣称。
- 可选增强（按需开启，需先登记到本文件）：`CODEOWNERS`（评审归属）、`dependabot.yml`（依赖升级）、`pip-audit` 依赖扫描（`SECURITY.md` §3 已列）。
