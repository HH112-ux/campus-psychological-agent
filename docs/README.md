# 文档索引

本目录是「心屿」项目文档的唯一入口。所有文档使用纯 Markdown（`.md`），命名遵循 kebab-case，仓库规则见 [repo-governance.md](repo-governance.md)。

> **关于历史审查记录**：本目录保留了多轮代码审查与健康度评估报告，用于留痕与复盘。它们**仅代表审查当时（对应 commit）的状态，不代表当前代码**；请以当前代码、测试与 [README](../README.md) 为准。

## 设计与规范

| 文档 | 说明 |
|---|---|
| [repo-governance.md](repo-governance.md) | 仓库治理：命名、文件格式、Git/GitHub 同步与入库规则 |
| [ui-style-guide.md](ui-style-guide.md) | 小程序视觉规范（主题「暖暮 · 屿」） |
| [ui-redesign-diagnosis.md](ui-redesign-diagnosis.md) | 界面诊断与分期改造方案 |
| [ui-redesign-p0-execution.md](ui-redesign-p0-execution.md) | P0 改造执行记录（token、文案、空状态等） |
| [task-management.md](task-management.md) | 需求到任务的拆分规范（F1–F6） |
| [versioning.md](versioning.md) | 语义化版本与发布策略 |

## 开发与测试

| 文档 | 说明 |
|---|---|
| [architecture-dependency.mmd](architecture-dependency.mmd) | 模块依赖图（Mermaid） |
| [improvement-roadmap.md](improvement-roadmap.md) | 二期改进方案与逐项落地状态 |
| [beta-plan-p5.md](beta-plan-p5.md) | P5 内测方案（30–50 名学生） |
| [eval-gate.md](eval-gate.md) | 评估与回归门（E1）口径与阈值 |
| [emotion-eval-m3.md](emotion-eval-m3.md) | 情绪分类一致率首次测量 |
| [emotion-eval-p5.md](emotion-eval-p5.md) | 情绪分类一致率正式评估（P5） |
| [prompt-eval-v1-v2.md](prompt-eval-v1-v2.md) | 情绪分析提示词 V1 → V2 对比 |
| [memory-eval-v6.md](memory-eval-v6.md) | 长期记忆抽取稳定性评估（V6） |
| [crisis-recall-p5.md](crisis-recall-p5.md) | 危机信号召回验证（P5） |
| [eval-cost-p5.md](eval-cost-p5.md) | 压测与模型成本核对（P5） |
| [review-package-p5.md](review-package-p5.md) | 小程序提审材料包 |
| [bad-case-review-template.md](bad-case-review-template.md) | bad-case 双周复盘模板 |
| [../backend/README.md](../backend/README.md) | 后端本地开发、目录与接口自测 |
| [../miniprogram/README.md](../miniprogram/README.md) | 小程序导入、调试与提审注意 |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 开发流程与提交规范 |

## 部署与运维

| 文档 | 说明 |
|---|---|
| [prod-deploy-drill-2026-11-10.md](prod-deploy-drill-2026-11-10.md) | 生产编排（prod profile）本机部署演练 |
| [miniprogram-go-live-checklist.md](miniprogram-go-live-checklist.md) | 小程序上线部署可执行清单 |
| [../backend/README.md](../backend/README.md) | Docker Compose 部署、Nginx、证书挂载与镜像源说明 |

> 证书文件放在 `backend/nginx/certs/`（不入库）；生产 compose 使用 `prod` profile，并在内部固定网段内启用代理头信任。

## 合规与隐私

| 文档 | 说明 |
|---|---|
| [privacy-policy.md](privacy-policy.md) | 隐私政策终稿（数据处理、用户权利、留存与删除） |
| [../SECURITY.md](../SECURITY.md) | 安全策略：漏洞报告、密钥管理与数据保护 |

## 危机响应

| 文档 | 说明 |
|---|---|
| [crisis-response-sop.md](crisis-response-sop.md) | 高危风险事件人工响应 SOP |
| [crisis-lexicon-workflow.md](crisis-lexicon-workflow.md) | 危机词库变更流程（召回只许升、不许降） |

## 历史审查记录

> 以下均为**历史审查留档，不代表当前状态**。按时间倒序排列。

| 文档 | 时间 | 对应 commit | 说明 |
|---|---|---|---|
| [launch-readiness-review-2026-11-11.md](launch-readiness-review-2026-11-11.md) | 2026-11-11 | `8f87bfa` | 第 10 轮上线就绪度全量审查 |
| [code-review-recheck-round9-2026-11-08.md](code-review-recheck-round9-2026-11-08.md) | 2026-11-08 | `e90f9bf` | 第九轮完整代码审查 |
| [code-review-recheck-round8-2026-11-06.md](code-review-recheck-round8-2026-11-06.md) | 2026-11-06 | `a8b71c8` | 第八轮定向复核（断句口径） |
| [code-review-recheck-round7-2026-11-06.md](code-review-recheck-round7-2026-11-06.md) | 2026-11-06 | `1c299f1` | 第七轮定向复核（碰撞豁免） |
| [code-review-recheck-round6-2026-11-06.md](code-review-recheck-round6-2026-11-06.md) | 2026-11-06 | `527a346` | 第六轮复审 |
| [code-review-recheck-round5-2026-11-06.md](code-review-recheck-round5-2026-11-06.md) | 2026-11-06 | `cb8b891` | 第五轮复审收口 |
| [code-review-recheck-round4-2026-11-06.md](code-review-recheck-round4-2026-11-06.md) | 2026-11-06 | `41f64fb` | 第四轮复审 |
| [code-review-recheck-round3-2026-11-06.md](code-review-recheck-round3-2026-11-06.md) | 2026-11-06 | `84deafd..HEAD` | 第三轮复审 |
| [code-review-recheck-round2-2026-11-06.md](code-review-recheck-round2-2026-11-06.md) | 2026-11-06 | `9e3f94c..84deafd` | 第二轮复审 |
| [code-review-recheck-2026-11-06.md](code-review-recheck-2026-11-06.md) | 2026-11-06 | 两批整改提交 | 首轮整改复审 |
| [code-review-2026-11-06.md](code-review-2026-11-06.md) | 2026-11-06 | 审查当时 HEAD | 首轮代码审查 |
| [tech-debt-health-review-2026-10.md](tech-debt-health-review-2026-10.md) | 2026-10 | — | 技术债与健康度中检 |
| [brooks-health-report.md](brooks-health-report.md) | — | — | brooks-lint 健康度看板 |
