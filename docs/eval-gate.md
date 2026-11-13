# 评估与回归门（E1）

> 状态：已生效 v1.0（2026-10-16）
> 目的：让「大模型表现」像单元测试一样有闸门——任何 LLM 相关改动（提示词、模型、解析器、链路）合入前，一致率不得低于阈值。

## 1. 回归门是什么

| 门 | 入口 | 阈值 | 运行环境 |
|---|---|---|---|
| 单元/集成测试 | `pytest -q`（含危机拦截双链路、内容安全 8 项） | 全绿 | 本地 + CI `backend` job（每次 push/PR） |
| 小程序语法门 | `node --check` 全量 JS | 全绿 | 本地 + CI `miniprogram` job |
| **情绪一致率回归门** | `python scripts/eval_emotion_p5.py --gate --require-key` | **严格一致率 ≥ 80%** | 本地随时；CI `eval` job（必须配置 `ZHIPU_API_KEY` secret，缺失即 job 失败） |
| **长期记忆抽取回归门（V6）** | `python scripts/eval_long_memory.py --gate --require-key` | **综合命中率 ≥ 80%**（正向命中类别+关键词、对抗输出空） | 同上，CI `eval` job 同步执行 |

## 2. 用法

```bash
cd backend
./.venv/bin/python scripts/eval_emotion_p5.py          # 出报告 docs/emotion-eval-p5.md，退出 0
./.venv/bin/python scripts/eval_emotion_p5.py --gate   # 回归门：< 80% 退出 1
./.venv/bin/python scripts/eval_long_memory.py          # 出报告 docs/memory-eval-v6.md，退出 0
./.venv/bin/python scripts/eval_long_memory.py --gate   # 回归门：< 80% 退出 1
# 门禁场景（CI）：缺 ZHIPU_API_KEY 时显式失败而不是 SKIP
./.venv/bin/python scripts/eval_emotion_p5.py --gate --require-key
./.venv/bin/python scripts/eval_long_memory.py --gate --require-key
```

- 评估集：`backend/scripts/eval-data/emotion_eval_v2.json`（65 条：四类 16/18/18/13 + 对抗 11 + 语音转写噪声 6，含黄金强度标注）。
- 长期记忆评估集：`backend/scripts/eval-data/memory_eval_v1.json`（18 条：正向 12 覆盖人物/事件/偏好/情绪诱因 + 对抗 6：一次性情绪、危机内容、闲聊、琐事、反讽、他人事件）。
- 链路与线上一致：`glm-4-flash`、temperature 0.2、同一系统指令与解析器（`app/services/emotion.py`、`app/services/long_memory.py`）。
- 报告每次运行都会重写 `docs/emotion-eval-p5.md` 与 `docs/memory-eval-v6.md`——它们是**滚动基线**，重大口径变化时单独留档（如 M3 首测 `emotion-eval-m3.md`）。

## 3. CI 行为

- `eval` job 每次 push/PR 触发；`ZHIPU_API_KEY` 从仓库 Secrets 注入，命令带 `--require-key`。
- **未配置 secret**：脚本打印 `FAIL` 退出 1，job 失败——评估门不允许静默跳过。
- 评估成本：65 条 × `glm-4-flash` × 200 max_tokens + 18 条（长期记忆）× 300 max_tokens，单次可忽略。

### 3.1 fork PR 的实际行为与处理策略

**实际行为**：GitHub 对来自 fork 的 `pull_request` 事件**不会注入仓库 Secrets**，因此 `ZHIPU_API_KEY` 为空；`--require-key` 让 `eval` job 在 fork PR 上**必然失败**，日志为：

```text
FAIL: 未配置 ZHIPU_API_KEY，评估门要求真实评估（--require-key），拒绝静默跳过
```

这是预期行为，不是脚本缺陷，也不是 secret 配置错误。首次贡献者的 PR 还需要维护者先批准才会运行 workflow。

**为什么保留 `--require-key`**：另一条路是把缺 key 当作 `SKIP` 退出 0，那样「eval 通过」会在没有任何真实评估发生的情况下变绿，评估门等于失效。宁可红，不可假绿。

**维护者处理（二选一，必须留痕）**：

1. **镜像到本仓库分支（首选，适用于任何 PR）**：由维护者把 fork 的提交拉到本仓库分支，在内部 PR 上触发 CI；secret 正常注入，eval 真实运行，合入以内部 PR 为准，原 fork PR 关闭并附链接。

   ```bash
   git fetch origin pull/<PR号>/head:pr-<PR号>
   git push origin pr-<PR号>:review/pr-<PR号>
   gh pr create --base main --head review/pr-<PR号> \
     --title "<原标题>（镜像 #<PR号>）" \
     --body "镜像自 #<PR号>：fork PR 无法获得仓库 secret，改由本仓库分支让 eval 门真实运行。"
   ```

2. **本地代跑 + 显式豁免（仅限不触碰 LLM 路径的 PR）**：维护者用自己的 key 在干净 checkout 上跑两条门禁命令，把输出尾部贴到 PR，再视 `eval` 是否为必需检查决定是否管理员合并。

   ```bash
   cd backend
   .venv/bin/python scripts/eval_emotion_p5.py --gate --require-key
   .venv/bin/python scripts/eval_long_memory.py --gate --require-key
   ```

   豁免条件：改动不涉及 `backend/app/llm/`、`backend/app/services/emotion.py`、`backend/app/services/long_memory.py`、`backend/scripts/eval-data/` 与评估脚本；豁免评论必须写明被验证的 commit SHA、两条命令的严格一致率/综合命中率，以及执行人。

**禁止做法**（会把密钥或门禁交给不可信代码）：

- 改用 `pull_request_target` 并 checkout fork 的 head：secrets 会暴露给 fork 代码，等于把 `ZHIPU_API_KEY` 交给任意贡献者；
- 去掉 `--require-key`、加 `continue-on-error`、把缺失 key 改回 `SKIP`：评估门变假绿；
- 在 fork 仓库配置同名 secret：上游 PR 的 `pull_request` 工作流不会使用它，既解决不了红灯，也扩大了密钥暴露面。

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
