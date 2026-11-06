# 「心屿」小程序 P0 改造执行记录

> 范围：P0 值/文案级改造（token 收敛、会话上限口径、每日一句轮换、空状态改造、规范同步）。
> 未做：页面结构重排、图标体系替换（P1）、TabBar 图标（P1）。未改动 backend 业务逻辑，未引入任何组件库。
> 基线：`docs/ui-redesign-diagnosis.md`、`docs/ui-style-guide.md`。

---

## 一、已完成项（改动文件清单 + 关键 before/after）

### 1. 设计令牌收敛（`app.wxss`）

新增并固定 6 档字阶、3 档圆角、3 档动效，另补品牌投影与遮罩令牌：

| 类别 | before | after |
|---|---|---|
| 圆角 | `--radius-md: 22rpx` / `--radius-sm: 16rpx` | `--radius-md: 20rpx` / `--radius-sm: 12rpx`（+ lg 28rpx，共 3 档） |
| 字阶 | 无令牌，各页写字面值（实测 19 档） | `--fs-display 40 / --fs-h2 32 / --fs-body 30 / --fs-body-s 28 / --fs-caption 24 / --fs-micro 22` |
| 动效 | 无令牌，页面写 `0.1s` | `--dur-fast 120ms / --dur-base 240ms / --dur-slow 400ms` |
| 阴影 | card / soft 两档 | + `--shadow-brand`（呼吸圆、新建按钮）、+ `--scrim`（弹层遮罩） |
| 全局字号 | `font-size: 30rpx` | `font-size: var(--fs-body)` |

### 2. 各页接入令牌

| 文件 | 关键改动 |
|---|---|
| `pages/index/index.wxss` | 大标题 44rpx → `--fs-display`；卡片标题 34 → `--fs-h2`；`transition .1s` → `var(--dur-fast)` |
| `pages/chat/chat.wxss` | 24/27/30/26rpx → 对应 4 档；发送/麦克风 `36rpx` 圆角 → `999rpx` 胶囊；`12rpx` 圆角 → `--radius-sm` |
| `pages/logs/logs.wxss` | 27/26/30rpx 收敛；chip `32rpx` → `999rpx`；柱状图/证据块 `8/10rpx` → `--radius-sm`；徽章 `36rpx` → `50%` |
| `pages/mine/mine.wxss` | 头像 `52rpx` → `50%`；字号 36/30/24rpx → 3 档令牌 |
| `pages/sessions/sessions.wxss` | **大标题 64rpx/800/字距 4rpx → `--fs-display` 40/600**（与首页统一）；`31rpx` → `--fs-h2`；`25rpx` → `--fs-caption`；新建按钮阴影 → `var(--shadow-brand)` |
| `pages/memories/memories.wxss` | 全页 26/24/28rpx → 4 档；删除废弃 `.empty-icon`；新增 `.empty-action` |
| `pages/practice/practice.wxss` | **整页字面色值清零**：`#3e7a69/#7a736b/#2f2a24/#9c936b/#9c5722/#ffffff/#f7f4ef` 与 `rgba(62,122,105,.1/.12)` → 全量接入令牌；卡片阴影 `rgba(156,87,34,.08)` → `--shadow-card`；圆角 24/18/22/32rpx → md/sm/md/lg |
| `components/crisis-card/crisis-card.wxss` | 字面字号对齐 6 档（40→32、34→32、27→28、29→30、23→24、28→30）；**色值保留**（见 §三 例外说明） |

### 3. 会话上限口径统一为单一来源（=5）

依据：`backend/app/config.py:52` `session_concurrency_limit: int = 5`（后端实际配置，前端不再各自写死）。

| 位置 | before | after |
|---|---|---|
| `utils/api.js` | 无 | 新增 `SESSION_CONCURRENCY_LIMIT: 5`（前端唯一口径） |
| `pages/sessions/sessions.wxml:5` | 「最多保留 3 个」 | 「最多保留 `{{sessionLimit}}` 个」 |
| `pages/sessions/sessions.js` | `>= 15` + 文案「15 个」 | `>= api.SESSION_CONCURRENCY_LIMIT` + 模板串 |
| `pages/chat/chat.js:72` | 文案「3 个」 | 模板串引用常量 |

### 4. 「每日一句」改为本地按日轮换

`pages/index/index.js`：编译期常量 `DAILY_QUOTE` → `DAILY_QUOTES`（14 条合规文案，不含诊断/治疗承诺/鸡血）+ `todayQuote()` 以「年内第几天 % 14」取值；`onShow` 中比较并刷新（跨零点回前台即更新，同一天内稳定）。**不新增网络请求、不调模型。**

### 5. 空状态改造（emoji → 引导文案 + 下一步入口）

| 页面 | before | after |
|---|---|---|
| `logs.wxml` | `🌱` + 「和我说说今天，日志会自动长出来」 | 「还没有记录。从今天的一次打卡开始吧」+「去打卡」（`goCheckin` → `wx.switchTab` 首页） |
| `sessions.wxml` | `🌱` + 「还没有对话，从上方…说起吧」 | 「还没有对话。把此刻想说的话，讲给小屿听吧」+「开始一段新对话」 |
| `memories.wxml` | `🏝` + 「和我多聊聊吧——…我会温柔地记住。」 | 「聊得多了，这里会留下你提到过的人和事」+「去聊聊」（`goChat` → 对话页） |
| `logs.wxss / sessions.wxss / memories.wxss` | `.empty-emoji{72rpx}` / `.empty-icon{72rpx}` | 删除上述规则，新增 `.empty-action`（胶囊、`--brand` 底白字） |

### 6. 情绪色迁出 JS

`pages/logs/logs.js`：`EMOTION_META` 的 `color: '#e06666'` 等 6 个色值 → `cls: 'anxious'` 等语义类；装饰结果由 `color` 改为 `colorClass`；`logs.wxml` 的 `style="background: {{item.color}}1A; color:…"` → `class="tl-badge tl-badge--{{item.colorClass}}"`；色值唯一定义于 `logs.wxss` 的 12 条 `.tl-*--<cls>` 规则。

### 7. 规范同步（`docs/ui-style-guide.md`）

- §1.7 情绪色表改为「类名 + 唯一来源在 wxss，JS 不得持色」；
- §2 字阶改为 6 档令牌表，废止 64rpx/800 与 44/34/32/26rpx 旧档，写明两类功能性例外；
- §3 圆角改为「3 档 + 3 类特例」，阴影增补 `--shadow-brand`、`--scrim`；
- §4.1 渐变按钮阴影改用令牌；
- §4.7 空状态规则由「居中 emoji 72rpx」改为「引导文案 + 下一步入口」，并禁用空泛比喻/承诺式文案；
- §6 新增 3 档动效表与功能性动画豁免；
- §8 文件索引按本次实际改动重写。

---

## 二、修复项（接管时发现的半成品）

1. `practice.wxss` 完全未改（上一轮中断前未落盘）——已全量接入令牌。
2. `memories.wxss` 完全未改，且 `memories.wxml` 已删 `🏝` 但 wxss 仍留 `.empty-icon`（死规则）——已清理并补 `.empty-action`。
3. `docs/ui-style-guide.md` 尚未更新——已按 §7 重写对应条目。
4. `crisis-card.wxss` 字号仍为 23/27/29/34/40rpx 非档位值——已对齐 6 档（保持字面值，见下）。
5. 上一轮写入 `practice.wxss` 若存在重复 `.done-tag`——已合并为单条规则。

**回退项：无。** 未发现需要回退的破坏性改动。

---

## 三、保留的字面色值/圆角例外及理由

| 位置 | 保留内容 | 理由 |
|---|---|---|
| `components/crisis-card/crisis-card.wxss` | 全部色值（`#C1342A`、`#9C6218`、暖红/琥珀底、暖灰字） | 组件默认 `styleIsolation: isolated`，不依赖 `page` 上的变量继承；危机卡片是安全功能，色值即语义、不可被主题同化。**Danger 红/Amber 强度未做任何弱化。** |
| 同上 | 圆角 `28/20/999rpx`、字号 `22/24/28/30/32rpx` | 均为区间内合法档位（lg/md/胶囊；6 档字阶），仅写成字面值而非变量 |
| `logs.wxss` `.tl-*--<cls>` 12 条 | 情绪语义色 | 由 JS 迁入的**唯一**色彩来源，反向依赖令牌会丢掉情绪区分度 |
| `chat/sessions/mine/index/practice/memories.wxss` | `color: #fff / #ffffff`、`#f2f7f5` | 饱和底上的纯白前景，不属主题色漂移 |
| emoji 字形位：`index 40/48/56rpx`、`logs 36rpx`、`mine 36rpx` | 字面字号 | P1 图标体系替换前的过渡，替换后删除（代码内已注释） |
| `practice.wxss .timer 56rpx` | 字面字号 | 功能性例外：220rpx 呼吸圆内需远距离可读（代码内已注释） |

---

## 四、残留未做项

| 项 | 原因/去向 |
|---|---|
| TabBar 无图标（`app.json` 4 个 tab 仅 text） | P1，需新增 8 枚 PNG |
| emoji 图标体系（情绪五档、我的页 6 个 cell、🎤、🔥、🧸） | P1 |
| 首页「六卡等距」结构重排、渐变收敛（头像/新建按钮） | P1 |
| 「同学」称呼、`chat.wxml` 常驻 `0/2000` 字数、「近 7 天情绪强度（1–10，无记录日跳过不补 0）」括号说明、「🔥 已连续记录 N 天」语气 | 属诊断报告 P0-5 文案批次，但不在本次「严格限定 P0」的四项范围内，留待文案批次统一处理 |
| 空状态插画（替代 emoji 的线条小插） | P2 |
| 卡片入场动效 | P2（令牌已就绪，未加动画） |

---

## 五、验证记录（实际执行的命令与结果）

| 检查 | 命令 | 结果 |
|---|---|---|
| JS 语法 | `for f in miniprogram/pages/*/*.js miniprogram/utils/api.js; do node --check "$f"; done` | 全部通过（无输出错误） |
| JSON 可解析 | 逐文件 `node -e "JSON.parse(...)"`（12 个 json） | 12/12 通过 |
| 变量完整性 | 对比 `grep -o "var(--…)"` 与 `app.wxss` 的 `--x:` 定义 | 38 个被引用变量全部有定义，无悬空引用 |
| 字面字号残留 | `grep -rn --include='*.wxss' -E "font-size: *[0-9]+rpx"` | 仅剩 crisis-card（对齐档位）与 6 处已注释的功能性例外 |
| 字面圆角残留 | `grep -rn --include='*.wxss' -E "border-radius: *[0-9]+rpx"` | 仅剩 28/20/999rpx（均为合法档位/胶囊） |
| 字面颜色残留 | `grep -rn --include='*.wxss' -E "#[0-9a-fA-F]{3,8}\|rgba?\("` | 仅剩 §三 例外项与 `#fff` 前景色 |
| 括号配平/声明分号 | 自写 node 脚本扫描全部 wxss | 括号配平；「缺分号」均为 `; /* 注释 */` 正则误报 |
| WXML 类名 ↔ 样式 | 自写 node 脚本比对 `class` 与 wxss/app.wxss | 无缺失（`crisis-card--`、`tl-badge--` 为动态拼接，取值均存在）；`trend-title` 为既有无样式包裹层，无视觉影响 |
| 重复规则 | 按选择器统计重名 | 无重复定义（`.btn-main,.btn-ghost` 为共用属性组，非冲突） |
| 空白字符 | `git diff --check` | 通过 |

**微信开发者工具**：本机无 GUI 开发者工具可用，**未做真机/模拟器编译**；以上为静态检查。建议在开发者工具中复核：首页情绪项选中上浮、日志时间线五色区分、练习弹层圆角与计时数字、三个空状态入口跳转。
