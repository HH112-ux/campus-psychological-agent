# AGENTS.md — 本仓库的 AI 协作约定（HOTL 适配层）

> 本文件只回答「AI 助手在这里该怎么工作」，**不复述**既有规范。
> 与下列文件冲突时，以规范文件为准。

## 1. 权威来源（动手前先读）

| 文件 | 管什么 |
|---|---|
| `CONTRIBUTING.md` | 分支模型、Conventional Commits、合入前质量门、安全红线 |
| `docs/repo-governance.md` | 命名（kebab-case）、文档格式、入库/不入库、CI 门禁 |
| `docs/task-management.md` | 任务编号、任务卡片字段、完成定义（DoD） |
| `docs/versioning.md` | SemVer、里程碑 tag 与发版清单 |
| `SECURITY.md` | 密钥管理、依赖扫描、泄露应急 |
| `docs/crisis-lexicon-workflow.md` | 危机词库任何改动（含热更新）的五步闭环 |

## 2. HOTL 工作模型

Human-on-the-Loop：人给意图与约束，AI 在护栏内自主执行，高风险处停下等人工确认。

每个实现类任务至少定义三份契约：

1. **意图契约**：目标、约束、成功标准；
2. **验证契约**：每步如何证明做对了（命令、断言、观测值）；
3. **治理契约**：审批 gate、风险级别、回滚方式。

流程：设计 → 执行 → 自证 → 收口。

- 设计文档落在 `docs/designs/`，执行计划落在 `docs/plans/YYYY-MM-DD-<slug>-workflow.md`
  （目录在首次使用时创建；仍须遵守 kebab-case 与纯 Markdown）。
- 未通过验证契约不得宣称完成；回滚方式未写清不得进入执行。
- 以下改动一律视为高风险，必须人工 gate：认证与权限、加密与密钥、隐私与数据删除、
  危机判定与合规过滤、SSE 协议、依赖大版本升级、数据库 schema。
- 若所用助手提供 HOTL 技能，按序使用：设计 → 计划 → 线性执行 → 完成前验证 → 分支收尾。

## 3. 项目硬约束（不可协商）

1. **SDD（规格先行）**：先有规格与接口契约，再写实现；代码、测试、文档必须与规格一致，
   不一致时先改规格并留痕，不允许「代码为准、文档作废」。
2. **文档事实可验证**：`README.md` / `backend/README.md` 中的测试基线、依赖、命令、相对链接
   由 `backend/scripts/check_docs_facts.py` 与 CI 的 `docs` job 校验，写错即红；新增技术栈声明
   需同步登记到该脚本的依赖清单。
3. **确定性链路不得被模型层替换**：危机判定（词库、分级、短路话术）与合规过滤（诊断结论、
   药物推荐、疗效宣称）是确定性代码，不得迁入模型抽象或改变行为；任何改动必须补正反用例。
4. **SSE 协议不得改坏**：心跳帧、截断标记、断连后继续生成并落库，三者行为改变即视为回归。
5. **文档落盘**：新增文档放 `docs/`，kebab-case，纯 Markdown；不生成 HTML 文档，命名豁免见
   `docs/repo-governance.md`。
6. **测试基线以实跑为准**：当前 `1131 passed, 1 skipped`（共 1132 项，2026-11-11 实跑；
   口径为 MongoDB 可用、未设置 `REDIS_TEST_URL`）。基线变化必须同步改 README，否则文档门禁失败。
7. **模型层边界**：传输实现集中在 `backend/app/llm/`；LangChain 仅用于模型传输，不引入
   chain / memory / agent。`backend/tests/test_llm_boundary.py` 会拦截越界 import。

## 4. 验证命令（与 CI 等价）

```bash
# 后端：静态检查 + 全量测试
cd backend && ruff check . && pytest -q

# 小程序：全量 JS 语法门 + 单元测试
find miniprogram -name '*.js' -print0 | xargs -0 -n1 node --check
node --test miniprogram/tests/*.test.js

# 文档：README 事实校验（需 MongoDB；CI 的 docs job 同款命令）
cd backend && python scripts/check_docs_facts.py
```

CI 定义在 `.github/workflows/ci.yml`，含 `backend` / `miniprogram` / `eval` / `docs` 四个 job；
合入 `main` 前必须全绿。

## 5. 提交与协作

- 提交信息遵循 `CONTRIBUTING.md` 的 Conventional Commits（中文 subject），一个逻辑变更一个提交。
- 暂存用显式路径 `git add <file>`，提交前 `git status` 确认暂存区只有本次文件。
- 不 push、不 force、不跳过 hook；`main` 只经 PR 合入。
- 密钥只放 `backend/.env`（`gitignore` 已覆盖），不打印、不写入文档、不进日志。
