# 第七轮定向复核报告（2026-11-06）

- 审查对象：`1c299f1`（`fix(crisis): 碰撞豁免只校验整词完整，去掉词后尾巴约束`）
- 审查范围：仅危机模块及其回归，不铺开全量重审
- 取证方式：`git archive HEAD` 到 `/tmp/recheck7` 干净快照 + 独立 venv（仅 `requirements-dev.txt`）；探针与变异测试全部在仓库外，未改业务代码、未提交、未推送
- 对照基线：`527a346`（第六轮 HEAD，`/tmp/recheck6`）

## 结论速览

| 核查项 | 结论 |
| --- | --- |
| 8 条误报样本 | 通过：8/8 为 none |
| 9 条核心样本 | 通过：结论与第六轮完全一致 |
| 声称的副作用「我不 想死 → high」 | 属实；另发现 14 条同族由放行变拦截 |
| 完整词掩护后半句真危机 | 通过：后半句均独立命中（high / mid 符合分级） |
| `_COLLISION_T2S` 等长归并 | 通过：1:1 映射，无错位；繁简主写法均正确 |
| 空白/零宽断句 | 有副作用：15 条 none→high，全部为误报方向 |
| 白名单繁简自检测试 | 通过：两种变异（缺繁体词 / 繁体写法错误）都会红 |
| 全量危机语料 107 条 + 记忆语料 35 条 | 0 条不符 |
| 干净快照 ruff / pytest | 通过：`All checks passed!`、`880 passed, 1 skipped` |
| miniprogram 契约 | 未受影响：本提交只改后端危机判定内部逻辑 |

**阻断：0 条。** 详见第四节。

---

## 一、修复核实

### 1.1 八条误报样本

| 输入 | 期望 | `detect_risk` / `contains_crisis_terms` |
| --- | --- | --- |
| 我不想活动只想躺着 | none | none / False |
| 我不想活动也不想说话 | none | none / False |
| 我不想活跃只想安静 | none | none / False |
| 我不想活躍，只想休息 | none | none / False |
| 我今天不想活蹦乱跳 | none | none / False |
| 不想活蹦乱跳了 | none | none / False |
| 我不想活跳跳 | none | none / False |
| 寻死觅活但我没事 | none | none / False |

第六轮 B-1 的 8 条误报全部闭环。

### 1.2 九条核心样本

| 输入 | 期望 | 实测 |
| --- | --- | --- |
| 我真的不想活，走不动了 | high | high |
| 不想活，走路都没力气 | high | high |
| 不想活。动不动就想哭 | high | high |
| 我不想活动 | none | none |
| 我不想动弹 | none | none |
| 我不想走动 | none | none |
| 不想活了 | high | high |
| 不想活下去 | high | high |
| 寻死 | high | high |

与第六轮逐条一致，`contains_crisis_terms` 同口径。

### 1.3 声称的副作用与相邻表达

「我不 想死」实测为 **high**，声称属实。旧版本（`527a346`）为 none，变化来自空白被纳入 `_CLAUSE_BREAK_RE`：`_raw_before` 在空格处截断，否定词「不」不再与「想死」同段。

新旧对照共发现 **15 条 none→high**：

| 类别 | 输入 | 旧 | 新 |
| --- | --- | --- | --- |
| 否定被空白/零宽切断 | 我不 想死 | none | high |
| | 我不 想自杀 | none | high |
| | 我没有 想死 | none | high |
| | 我没 想过要自杀 | none | high |
| | 我 没 想 过 自 杀 | none | high |
| | 我 不 想 死 | none | high |
| | 我不　想死（全角空格） | none | high |
| | 我不\u200b想死（零宽） | none | high |
| 寒暄被切断 | 我想死 你了 | none | high |
| | 我想死\u200b你了 | none | high |
| 夸张被切断 | 热得 要死了 | none | high |
| | 热得\u200b要死了 | none | high |
| 白名单词被切断 | 我不想活 动 | none | high |
| | 我不想活\u200b动 | none | high |
| | 我不想活　动 | none | high |

对照未变项：`我不想死`、`我没想过自杀`、`我不想自杀`、`我没想过要自杀` 仍为 none；`我不 太 想活` 因归一化后不含连续的「不想活」而为 none。

**判定**：全部是误报方向（多报，不漏报），不构成安全风险；但会让「我不 想死」「我想死 你了」这类输入直接短路到 high 危机回复（high 分支不调用大模型）。属于本轮已知副作用，建议按 4.3 处理。

---

## 二、新机制漏洞核查

### 2.1 去掉「词后必须是句读」后是否出现新漏报

完整词命中后不再看词后内容，理论上可能把「不想活动 + 后半句真危机」一起吞掉。实测：

| 输入 | 实测 | 说明 |
| --- | --- | --- |
| 我不想活动了，我想死 | high | 后半句独立命中 |
| 我不想活动，活着没意思 | mid | 「活着没意思」是 L2，mid 为正确分级 |
| 我不想活动也不想活 | high | 句尾「不想活」独立命中 |
| 我不想活动，但我真的不想活了 | high | 独立命中 |
| 我不想活动。我想死 | high | 独立命中 |
| 我不想活动，我想自杀 | high | 独立命中 |
| 我不想活动只想死 | high | 独立命中 |
| 我不想活跃，我想死 | high | 独立命中 |
| 我不想活蹦乱跳，我想死 | high | 独立命中 |
| 寻死觅活，其实我想死 | high | 独立命中 |
| 我不想活动但我真的不想活了 | high | 无标点也能独立命中 |
| 我不想活动也不想活只想死 | high | 独立命中 |

结论：豁免只作用于那一次命中的完整词，`_find_hits` 会继续扫描后续出现位置；**没有发现因去掉尾巴约束而产生的新漏报**。`我不想活动，活着没意思` 为 mid 而非 high，是因为后者本身是 L2 词，符合现行分级，不是漏判。

### 2.2 `_COLLISION_T2S` 等长归并

映射为 `動→动、躍→跃、亂→乱、尋→寻、覓→觅`，全部 1:1，`str.translate` 不会改变长度，不存在下标错位。

| 输入 | 实测 |
| --- | --- |
| 我不想活動 | none |
| 我不想活躍 | none |
| 我不想活蹦亂跳 | none |
| 我不想活跳跳（繁简同形） | none |
| 尋死覓活 / 尋死覓活但我沒事 | none |
| 不想活躍动（混排、长度 5） | none |
| 不想活躍动了 | none |
| 不想活蹦亂跳只想躺著 | none |
| 不想活亂跳（非白名单词） | high |
| 我不想活 動（空格打断） | high |

- 混排「不想活躍动」：按白名单词「不想活跃」取 4 字窗口归并后命中，尾部「动」不参与，不会错位；该写法本身不是规范词，none 可接受。
- 「不想活亂跳」不在白名单，high 属预期（不是「活蹦乱跳」的合法变体）。
- 未发现归并导致的错位或跨词误匹配。

### 2.3 断句字符集扩充到空白与零宽

- 自然断行：`我\n不想活了`、`我最近很好\n不想活了` 仍为 high，正常。
- 大量全角空格：`我　　　　不想活了` 仍为 high，无异常。
- 副作用集中在「否定/寒暄/夸张/白名单词被空白或零宽切开」的 15 条，见 1.3。
- 零宽字符（`\u200b/\u200c/\u200d/\ufeff`）与空白被当作断句后，`我不\u200b想死` 变 high、`我不想活\u200b动` 变 high；方向是多报。

### 2.4 白名单繁简自检测试是否真的会红

在 `/tmp/recheck7_mut` 临时副本验证，仓库文件未动。

**变异一：只加简体、不加繁体写法**

在 `_COLLISION_WORDS["不想活"]` 末尾加入 `"不想活受罪"`：

```text
FAILED tests/test_crisis.py::test_collision_forms_cover_every_whitelisted_word
1 failed, 114 deselected
Full diff:
  {
      '不想活动',
-     '不想活受罪',
      '不想活跃',
      ...
  }
```

**变异二：繁体写法错误**

把 `COLLISION_FORMS["不想活动"]` 的繁体从 `不想活動` 改成 `不想活凍`：

```text
FAILED tests/test_crisis.py::test_collision_forms_cover_every_whitelisted_word
AssertionError: '不想活凍' 未归并到 '不想活动'
1 failed, 109 deselected
```

结论：自检有效，既覆盖「新增词未补写法」，也覆盖「繁体写法与映射不一致」。

---

## 三、回归

### 3.1 全量语料

```text
crisis cases: 107, mismatches: 0
memory cases: 35, mismatches: 0
```

对应测试模块：

```text
tests/test_redline_regression.py   531 passed
tests/test_crisis.py               110 passed
```

### 3.2 干净快照实跑

```bash
git archive HEAD | tar -x -C /tmp/recheck7
cd /tmp/recheck7/backend
python3.12 -m venv .venv
.venv/bin/pip install -q -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
```

```text
All checks passed!
880 passed, 1 skipped, 1 warning in 3.94s
SKIPPED [1] tests/test_ratelimit_redis.py:170: 未设置 REDIS_TEST_URL，跳过真 Redis 集成测试
```

### 3.3 miniprogram 契约

- `git show --name-only 1c299f1` 只涉及 `backend/app/services/crisis.py`、`backend/tests/redline_corpus.py`、`backend/tests/test_crisis.py`，没有 API、模型或 miniprogram 改动。
- 危机卡片 payload 仍是 `{"level", "show_card", "resources"}`（`crisis.py:436-440`），SSE `crisis` 事件与 `crisis_high_shown` / `crisis_mid_shown` 字段未变；miniprogram 的 `crisis-card` 与 `chat.js` 消费路径无需调整。
- 结论：miniprogram 侧未受影响。

---

## 四、结论

### 4.1 是否还有阻断上线的问题

**0 条阻断。**

- 8 条误报全部修复；9 条核心样本结论不变。
- 没有发现新的漏报：完整词后的真危机均能独立命中；全量 107 条危机语料、35 条记忆语料 0 条不符。
- 繁简等长归并无错位、无误匹配；断句字符集扩充没有造成漏报。
- 自检测试两种变异都会红。
- ruff 与全量 pytest 通过；miniprogram 契约未变。

需要明确记录的一个非阻断副作用：空白/零宽被当作断句后，出现 15 条 none→high（否定、寒暄、夸张、白名单词被空格/零宽切开）。方向是多报，不是漏报，不构成安全阻断，但会让「我不 想死」「我想死 你了」直接进入 high 危机分支。

### 4.2 上线判断

**当前代码可以进入上线评估。**

进入上线评估后，仍需完成以下非代码前提（沿用已知，不新编）：

1. 小程序主体与心理服务类目资质；
2. 已备案 HTTPS 域名与证书；
3. 隐私政策、用户协议公示；
4. 微信提审与 48 小时审核响应安排；
5. 校方心理中心转介对接：值班人、备班人、校方对接人仍为 `[待填]`，需补齐 SLA 与联系链路；
6. 生产初始化：MongoDB / Redis、密钥、索引、危机词库 seed、告警 webhook。

### 4.3 剩余问题：上线前必须做 / 上线后迭代

**上线前必须做**

1. 空白/零宽的断句副作用（15 条 none→high）。建议把断句集拆成两套口径：
   - 词跨度/完整词判断继续用「标点、引号、括号、零宽」断句；
   - 否定词、寒暄、夸张的距离判断只按**标点/换行**断句，空白与零宽视为透明。
   这样可同时保留「我不想活〜动」的 high 与「我不 想死」「我不想活 动」的 none，且不影响第六轮三条漏报的修复。修完必须回归 1.1、1.2、2.1 的样本。
2. 把上述 15 条副作用样本补进 `CRISIS_CASES` / `MEMORY_CASES`，防止后续再改断句集时无声回归。

**上线后迭代**

1. 白名单边界继续补：`不想活泼 / 不想活潑`、`不想活受罪` 等仍为 high（旧版本即如此，非本轮引入），可按线上语料评估是否纳入。
2. `_COLLISION_T2S` 目前只覆盖 `動/躍/亂/尋/覓`，后续新增白名单词时依赖自检测试提醒补映射；建议在词表旁保留一句维护说明。
3. 危机高/中分级的语义边界（如「活着没意思」为 mid）可结合运营数据继续调参。
4. 第六轮遗留的非危机项（单行 sanitize 分句、跨行引导词缺口、台湾商品名、根目录 ruff、流式抖动）不在本轮范围，按原计划推进。

---

## 附：本轮取证说明

- 干净快照：`/tmp/recheck7`（`git archive HEAD`），venv 只装 `requirements-dev.txt`。
- 对照快照：`/tmp/recheck6`（`527a346`）。
- 变异副本：`/tmp/recheck7_mut`（自检测试两种变异均在副本内完成并复原，仓库未改动）。
- 探针脚本：`/tmp/recheck7/probe7.py`、`cmp_old_new.py`、`corpus_check.py`，均在仓库外，未提交。
