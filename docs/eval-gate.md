# 评估与回归门（E1）

> 状态：已生效 v1.0（2026-10-16）
> 目的：让「大模型表现」像单元测试一样有闸门——任何 LLM 相关改动（提示词、模型、解析器、链路）合入前，一致率不得低于阈值。

## 1. 回归门是什么

| 门 | 入口 | 阈值 | 运行环境 |
|---|---|---|---|
| 单元/集成测试 | `pytest -q`（含危机拦截双链路、内容安全 8 项） | 全绿 | 本地 + CI `backend` job（每次 push/PR） |
| 小程序语法门 | `node --check` 全量 JS | 全绿 | 本地 + CI `miniprogram` job |
| **情绪一致率回归门** | `python scripts/eval_emotion_p5.py --gate` | **严格一致率 ≥ 80%** | 本地随时；CI `eval` job（仓库配置 `ZHIPU_API_KEY` secret 后真跑，未配置自动 SKIP 不阻塞） |

## 2. 用法

```bash
cd backend
./.venv/bin/python scripts/eval_emotion_p5.py          # 出报告 docs/emotion-eval-p5.md，退出 0
./.venv/bin/python scripts/eval_emotion_p5.py --gate   # 回归门：< 80% 退出 1
```

- 评估集：`backend/scripts/eval-data/emotion_eval_v2.json`（59 条：四类 14/17/16/12 + 对抗 11，含黄金强度标注）。
- 链路与线上一致：`glm-4-flash`、temperature 0.2、同一系统指令与解析器（`app/services/emotion.py`）。
- 报告每次运行都会重写 `docs/emotion-eval-p5.md`——它是**滚动基线**，重大口径变化时单独留档（如 M3 首测 `emotion-eval-m3.md`）。

## 3. CI 行为

- `eval` job 每次 push/PR 触发；`ZHIPU_API_KEY` 从仓库 Secrets 注入。
- **未配置 secret**：脚本打印 `SKIP` 退出 0，job 绿——不阻塞无 key 的贡献者；配置后即转为真门。
- 评估成本：59 条 × `glm-4-flash` × 200 max_tokens，单次可忽略。

## 4. 扩充约定（新增 LLM 能力 → 新增评估样本）

| 触发 | 动作 |
|---|---|
| 改提示词 / 换模型 / 改解析器 | 合入前本地跑 `--gate`；CI 红则不得合入 |
| 新增 LLM 能力（记忆注入 V6、语音转写 V5、备用模型 E2 等） | **同步扩充评估集**：为该能力新增样本（含对抗样本），并在报告「不一致明细」中跟踪 |
| 线上发现 bad-case（V1 反馈闭环导出） | 归类后回灌评估集，形成「发现 → 固化 → 回归」闭环 |

对抗样本保持在 ≥10 条（反讽/引用/转述/嘴硬），四类样本保持均衡。

## 5. 与其他质量门的关系

- 危机拦截**召回**由 `pytest tests/test_crisis.py`（34 项）确定性覆盖——不依赖 LLM，永远必跑。
- 情绪一致率门依赖真实 LLM 调用，允许「无 key 跳过」，但配置 secret 后与 pytest 同级：红即拒合。
- 阈值调整属于口径变更：需同时改 `STRICT_THRESHOLD`、本文档与 roadmap §5.2，并在 CHANGELOG 留痕。
