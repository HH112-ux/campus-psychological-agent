# 心屿小程序 · 视觉规范

> **主题代号：暖暮 · 屿**
> **适用范围**：微信小程序端（`miniprogram/`）
> **设计观点**：校园心理陪伴场景需要「安全、温暖、不被评判」的视觉氛围。原设计使用通用 SaaS 蓝 `#4C8BF5` + 冷灰底 `#F5F7FA`——这是心理健康类产品的"品类中位数默认"，传达的是效率工具感而非陪伴的温度。本规范改为**暖青绿主色 + 暖米白底 + 暖沙橘高光**，并统一形状、层次与状态语言。

---

## 一、色彩

设计令牌集中定义于 [`app.wxss`](../miniprogram/app.wxss) 的 `page` 选择器，所有页面通过 `var(--token)` 引用，保证一致性。

### 1.1 主色 · 屿青（疗愈、沉静、自然，呼应"岛屿/水"意象）

| 令牌 | 值 | 用途 |
|---|---|---|
| `--brand` | `#3E7A69` | 主按钮、用户气泡、选中态、链接、热线电话 |
| `--brand-ink` | `#2F6355` | 深色文字（浅色块上的标题/标签、会话页大标题） |
| `--brand-soft` | `#5E9C8A` | 渐变浅端（头像、主按钮）、打字动画点、柱状图浅端 |
| `--brand-tint` | `#EAF3EF` | 选中底色、每日一句卡底、操作 chip 底 |
| `--brand-tint2` | `#F1F8F5` | 已完成打卡卡底 |

### 1.2 强调色 · 暖沙橘（连续记录、鼓励、高光）

| 令牌 | 值 | 用途 |
|---|---|---|
| `--accent` | `#C97B3D` | 强调（备用） |
| `--accent-ink` | `#9C5722` | 连续打卡徽章文字、"连接不稳定"降级提示 |
| `--accent-tint` | `#FBF0E4` | 连续打卡徽章底 |

### 1.3 中性 · 暖白体系（替换原冷灰蓝）

| 令牌 | 值 | 用途 |
|---|---|---|
| `--bg` | `#F7F4EF` | 页面底色 |
| `--surface` | `#FFFFFF` | 卡片面 |
| `--surface-warm` | `#FDFCFA` | 微暖卡片面（备用） |
| `--input-bg` | `#F3F0EB` | 输入框、未选中项、证据块底 |
| `--line` | `#EDE9E3` | 分隔线、边框 |
| `--text` | `#2B2825` | 正文 |
| `--text-2` | `#6B655E` | 次要文字 |
| `--text-3` | `#7A736B` | 说明、时间戳、占位符 |
| `--disabled` | `#BFD1C9` | 禁用态填充 |

### 1.4 语义色（安全功能，**不得被主色同化、不得被暖底洗掉**）

| 令牌 | 值 | 用途 |
|---|---|---|
| `--danger` | `#C1342A` | 危机高危、错误、超字数、删除 |
| `--danger-tint` | `#FCEBE8` | 高危底色块 / 危险 chip 底 |
| `--warn` | `#9C6218` | 危机中危、警告 |
| `--warn-tint` | `#FDF3E2` | 中危底色块 |
| `--success` | `#2E7D4F` | 正向情绪 |
| `--success-tint` | `#E9F5EE` | — |
| `--info` | `#3D6AD6` | 平静 / 信息（保留蓝色，与主色明确区分） |
| `--info-tint` | `#E9EEFB` | — |

### 1.5 特殊场景色

| 令牌 | 值 | 用途 |
|---|---|---|
| `--memory-bg` | `#FBF4E6` | 记忆型问候卡（暖木色，制造"被记得"的温度） |
| `--memory-text` | `#7A6437` | 记忆卡文字 |

### 1.6 危机卡片专用色（组件内字面值，样式隔离下更稳妥）

| 层级 | 底色渐变 | 边框 | 徽章 | 电话/拨打 |
|---|---|---|---|---|
| 高危 high | `#FDF0EC → #FBE0D8` | `#F0AF9E` | `#C1342A` | `#C1342A` |
| 中危 mid | `#FDF8EE → #FBEED3` | `#EDD0A0` | `#9C6218` | — |

> 危机卡片的红 / 琥珀**语义与醒目度不做装饰性弱化**，仅做色相微暖与圆角统一。

### 1.7 情绪语义色与色点（唯一来源为 `styles/emotion.wxss` 的 `.emo--<cls>` 类）

`index.wxss` 与 `logs.wxss` 均以 `@import "../../styles/emotion.wxss";` 共用同一份定义，页面内不得再出现情绪色值或情绪色类。**五档差异只允许用样式维度表达**（内核浓度 `--emo-fill`、描边 `--emo-ring`、内间隙 `--emo-gap`、外环 `--emo-halo`），不得新增第五套 hex。

| 后端情绪词 | 类名 | `--emo-ink` | 视觉差异（色点） |
|---|---|---|---|
| 焦虑 `anxious` | `.emo--anxious` | `#e06666` | 内核 0.55 + 外扩细环（余波） |
| 烦躁 `angry` / `irritable` | `.emo--angry` / `.emo--irritable` | `#e0913e` | 4rpx 粗描边（紧绷）+ 内核 0.8 |
| 低落 `depressed` / `low` | `.emo--depressed` / `.emo--low` | `#6b7fa8` | 2rpx 描边 + 内核 0.25 + 6rpx 内间隙（下沉） |
| 平静 `calm` | `.emo--calm` | `#6fae7f` | 无描边 + 内核 0.85（饱满） |
| 还行 `ok` | `.emo--ok` | `#6fae7f` | 2rpx 描边 + 内核 0.4 |
| 其他 `other` | `.emo--other` | `#7a736b` | 2rpx 描边 + 内核 0.5 |

色点结构为 `.emo-glyph`（默认 40rpx / `--lg` 44rpx / `--sm` 28rpx）：`::after` 画内核，`::before` 画外环；底色取 `--emo-bg`，描边取 `--emo-ink`。

> **JS 不得持有色值**：`logs.js` 只输出语义 `colorClass`，`index.js` 只保留 mood key 与中文 label，渲染靠 class 绑定。打卡词汇（`low` / `irritable`）与对话词汇（`depressed` / `angry`）合并在同一条规则的双选择器里，新增一类情绪必须同时补 `.emo--<cls>`。
> **不以色独传信息**：色点旁必须有可读文字标签（`.mood-label` / `.done-line` / `.tl-label`）。

---

## 二、字体层级

字体族：`-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif`。字号统一使用 `rpx`，**只允许 6 档令牌**（`app.wxss` 定义），禁止在页面里写字面字号。

| 令牌 | 字号 | 字重 | 行高 | 用途 |
|---|---|---|---|---|
| `--fs-display` | 40rpx | 600 | 1.3 | 页面大标题 / 问候语（首页与会话页统一，废除 64rpx/800） |
| `--fs-h2` | 32rpx | 600 | 1.4 | 卡片标题、功能入口标题、底部弹层标题 |
| `--fs-body` | 30rpx | 400 | 1.6 | 正文、气泡、输入框、按钮 |
| `--fs-body-s` | 28rpx | 400 | 1.6 | 次要正文、日签、记忆问候、空状态说明 |
| `--fs-caption` | 24rpx | 400 | 1.5 | 时间戳、元信息、chip、次要说明 |
| `--fs-micro` | 22rpx | 400 | 1.5 | 字数统计、图例、角标 |

规则：
- 正文行高固定 `1.6`，保证长段落的可读性。
- 同一屏内不超过 3 个相邻字号层级，避免层级噪音。
- **允许的两类功能性例外**（需注释说明）：
  1. **非情绪 emoji 字形位**（36–72rpx）：仅剩 `mine` 的 `.cell-icon`（🌿/🏝）、`index` 的 `.memory-icon`（🧸）、`logs` 连续记录 🔥 与编辑 ✎，属图标体系替换前的过渡值；情绪五档已改为 `styles/emotion.wxss` 自绘色点，不再占用 emoji 字号；
  2. **练习计时数字** `56rpx`（`practice.wxss .timer`）：需在 220rpx 呼吸圆内远距离可读。
- 危机卡片组件内使用字面字号（样式隔离，不依赖变量继承），但数值必须对齐上表 6 档。

---

## 三、形状、间距与层次

圆角**只允许 3 档令牌 + 3 类特例**，禁止新增字面圆角：

| 令牌 | 值 | 用途 |
|---|---|---|
| `--radius-lg` | 28rpx | 大卡片（危机卡片）、底部弹层 |
| `--radius-md` | 20rpx | 标准卡片、气泡、输入框、主按钮 |
| `--radius-sm` | 12rpx | 小卡、内部色块、情绪项、徽章、证据块 |
| 特例 胶囊 | `999rpx` | 发送按钮、chip、操作标签、空状态入口按钮 |
| 特例 圆形 | `50%` | 头像、情绪色点、时间线徽章 |
| 特例 气泡指向角 | `8rpx` | 气泡单角（指向说话人） |

| 令牌 | 值 | 用途 |
|---|---|---|
| `--shadow-card` | `0 6rpx 20rpx rgba(63,58,50,.05)` | 标准卡片阴影 |
| `--shadow-soft` | `0 2rpx 10rpx rgba(63,58,50,.04)` | 轻卡片、列表项 |
| `--shadow-brand` | `0 16rpx 40rpx rgba(62,122,105,.25)` | 品牌投影：仅呼吸圆、新建会话主按钮等单点强调 |
| `--scrim` | `rgba(47,42,36,.45)` | 底部弹层遮罩 |

> 阴影使用**暖色透明**（`rgba(63,58,50,…)`）而非纯黑，与暖底调和。除上表外的阴影一律不再新增。

间距基线：

| 场景 | 值 |
|---|---|
| 页面左右内边距 | 32rpx |
| 卡片内边距 | 32rpx |
| 卡片间距 | 24rpx |
| 列表项间距 | 16–20rpx |
| 区块标题上间距 | 40rpx |

---

## 四、组件规范

### 4.1 按钮

| 类型 | 背景 | 文字 | 圆角 | 高度 |
|---|---|---|---|---|
| 主按钮 | `--brand` | `#FFFFFF` | sm / 胶囊 | 72–96rpx |
| 禁用 | `--disabled` | `#F2F7F5` | 同上 | 同上 |
| 危险操作 | `--danger-tint` 底 + `--danger` 字 | — | 999rpx | 自适应 |

渐变形主按钮：`linear-gradient(135deg, var(--brand), var(--brand-soft))`，阴影 `var(--shadow-brand)`。

### 4.2 卡片
`--surface` 底 + `--radius-md` + `--shadow-card` + `32rpx` 内边距。
带语义的卡片使用对应 tint 底色（日签 `--brand-tint`、记忆卡 `--memory-bg`、已完成打卡 `--brand-tint2`）。

### 4.3 对话气泡
- 用户：`--brand` 底 + 白字 + `--radius-md`，右上角 8rpx（指向自己）
- 小屿：`--surface` 底 + `--text` 字 + `--shadow-soft`，左上角 8rpx
- 最大宽度 76%，正文 30rpx/1.6

### 4.4 徽章 / 角标
胶囊形，tint 底 + 对应 ink 色文字：连续打卡（暖沙）、情绪角标（语义五色）、危机徽章（红/琥珀实底白字）。

### 4.5 输入框
`--input-bg` 底、`--radius-md`/`--radius-sm`、占位符 `--text-3`；字数提示按 §五 阈值触发（默认隐藏），仅在接近上限时出现在右下角，超限转 `--danger`。

### 4.6 头像
主色渐变 `linear-gradient(135deg, var(--brand), var(--brand-soft))` + 白色文字。尺寸：对话页 64rpx，我的页 104rpx。

### 4.7 空状态

**不使用 emoji 或插画占位**。统一为「一句具体引导文案 + 一个可点击的下一步入口」：

| 组成 | 样式 |
|---|---|
| 引导文案 | `--text-3`，`--fs-body-s`（28rpx）/1.7，说明「现在可以做什么」 |
| 下一步入口 | 胶囊按钮（`999rpx`），`--brand` 底 + 白字，`--fs-body-s`，点击直达可完成该动作的页面 |

现有实现：日志页 → 「去打卡」跳首页；会话页 → 「开始一段新对话」；记忆页 → 「去聊聊」跳对话页。
禁止空泛比喻或承诺式文案（如「我会温柔地记住」）。

---

## 五、文案原则（称呼 · 字数 · 语气）

1. **不叫「同学」，也不叫「用户 / 亲爱的」**：称呼统一落在「你」。首页按时段直接说话（「早，今天也来了」；深夜「夜深了，还没睡呀」），默认昵称兜底 `你`、缺省头像字 `屿`，AI 自称「小屿」。新增文案不得出现客服前缀或尊称。
2. **不把实现口径写给用户**：字数上限、情绪枚举值、接口名、补 0 规则一律不出现在界面。字数提示只在接近上限时出现，正向表述「还能写 N 字」，超限才转 `--danger` 并显示「超出 N 字」；阈值：对话输入 1800/2000 字，打卡备注剩余 40 字（即 160/200）。
3. **鼓励具体、允许中断**：不打鸡血，不用 🔥 式成瘾激励作文案主语；连续记录统一写「🔥 连续记录 N 天」，断签不提示失败、不追问原因。
4. **拟人化克制**：可以说「我都在」「我在听」，不承诺「一直 / 永远 / 随时」。
5. **说人话，不写解释性括号**：把规则改写成自然句（如「近 7 天的情绪起伏」），不出现「1–10」「无记录日跳过不补 0」这类实现说明。
6. **合规红线**：任何文案不得出现诊断、治疗、药物、疗效承诺；危机卡片与免责声明只允许更清楚，不允许弱化（见 §八）。

---

## 六、对比度校验（WCAG 2.1）

| 组合 | 比值 | 阈值 | 结论 |
|---|---|---|---|
| 正文 `#2B2825` / 底 `#F7F4EF` | 13.4:1 | 4.5 | ✅ |
| 正文 / 白卡 | 14.7:1 | 4.5 | ✅ |
| 次文 `#6B655E` / 白卡 | 5.8:1 | 4.5 | ✅ |
| 次文 / 页面底 | 5.3:1 | 4.5 | ✅ |
| 说明 `#7A736B` / 白卡 | 4.7:1 | 4.5 | ✅ |
| 说明 / 页面底 | 4.3:1 | 4.5 | ⚠️ 仅用于 22–24rpx 辅助文字 |
| 白字 / 主色 `#3E7A69` | 5.0:1 | 4.5 | ✅ |
| 主色字 / 白底 | 5.0:1 | 4.5 | ✅ |
| 深屿青 `#2F6355` / 屿青浅底 | 6.1:1 | 4.5 | ✅ |
| 暖沙 `#9C5722` / 暖沙浅底 | 4.9:1 | 4.5 | ✅ |
| 危险 `#C1342A` / 白底 | 5.5:1 | 4.5 | ✅ |
| 白字 / 中危徽章 `#9C6218` | 5.0:1 | 4.5 | ✅ |
| 白字 / 高危徽章 `#C1342A` | 5.5:1 | 4.5 | ✅ |

> 唯一边缘项是 `--text-3` 在页面暖底上的 4.26:1，实际使用场景多为白卡（4.7:1）上的辅助说明，可接受。

---

## 七、状态规范与动效

动效**只允许 3 档时长令牌**（`app.wxss` 定义），统一缓动 `ease`：

| 令牌 | 值 | 用途 |
|---|---|---|
| `--dur-fast` | 120ms | 按下 / 选中反馈（情绪项上浮） |
| `--dur-base` | 240ms | 卡片出现、弹层进出 |
| `--dur-slow` | 400ms | 氛围动效上限 |

> 功能性动画不受限：正在输入三点闪烁、呼吸练习的缩放（时长由 JS 相位驱动）。

| 状态 | 表达方式 |
|---|---|
| 默认 | 常规令牌 |
| 选中 | 主色 tint 底 + 主色边框/文字 + 轻微上移 `translateY(-6rpx)` |
| 按下 | `transition: transform var(--dur-fast) ease`（情绪项） |
| 禁用 | `--disabled` 底 + 低对比文字（按钮）、`opacity .55`（不可拨打热线） |
| 错误 / 超限 | `--danger` 文字（字数超限）、红色语义 badge |
| 降级 | `--accent-ink` 文字提示"连接不稳定，已为你保留" |

---

## 八、无障碍与安全底线

1. **危机卡片**是安全功能：红 / 琥珀的语义与醒目度不可被主题色弱化；high 与 mid 必须一眼可区分。
2. **语义色恒定**：绿=正向、红=危险/错误、橙黄=警告、蓝=信息，全站一致，不随氛围调整。
3. **不以色独传信息**：情绪、状态均以"颜色 + 文字/图标"共同表达。
4. **正文对比度 ≥ 4.5:1**，UI 元素 ≥ 3:1（已实测达标）。
5. 危机卡内"拨打"按钮与电话号使用 `--danger`，保证最高优先级视觉权重。

---

## 九、文件变更索引

| 文件 | 变更内容 |
|---|---|
| [`app.json`](../miniprogram/app.json) | 导航栏改暖米白底 + 黑色标题；tabBar 接入 `assets/tabbar/*` 图标，选中色 `#3E7A69`、未选中 `#7A736B`、底色 `#FDFCFA` |
| `miniprogram/assets/tabbar/*.png`（8 个） | TabBar 常态/选中图标，81×81 RGBA 透明底，由 `tools/gen_icons.py` 生成 |
| `miniprogram/assets/app-icon-{144,512}.png` | 应用图标，同一脚本生成 |
| [`tools/gen_icons.py`](../tools/gen_icons.py) | 图标绘制脚本（Pillow，8× 超采样），见 §十 |
| [`app.wxss`](../miniprogram/app.wxss) | 新增全部设计令牌；字阶 6 档、圆角 3 档、动效 3 档、阴影/遮罩令牌；页面底色 `#F7F4EF` |
| [`styles/emotion.wxss`](../miniprogram/styles/emotion.wxss) | **情绪视觉唯一来源**：`.emo--<cls>` 语义变量（`--emo-ink/bg/ring/fill/gap/halo`）+ `.emo-glyph` 色点（`--lg` / `--sm` 两档），纯 WXSS 绘制，无 emoji、无图片 |
| [`pages/index/index.wxss`](../miniprogram/pages/index/index.wxss) | 日签卡、记忆卡、打卡区、情绪项、入口卡接入字阶/圆角/动效令牌；`@import` 共用情绪样式，删除 `.mood-emoji` / `.done-emoji` |
| [`pages/chat/chat.wxss`](../miniprogram/pages/chat/chat.wxss) | 气泡、头像、情绪角标、输入区、发送/麦克风按钮接入令牌 |
| [`pages/logs/logs.wxss`](../miniprogram/pages/logs/logs.wxss) | 趋势卡、柱状图、筛选 chip、时间线接入令牌；`@import` 共用情绪样式，时间线徽章只消费 `var(--emo-bg)/var(--emo-ink)`，删除 `.tl-badge--*` / `.tl-label--*` 色值类 |
| [`pages/mine/mine.wxss`](../miniprogram/pages/mine/mine.wxss) | 资料卡、头像、热线电话接入令牌 |
| [`pages/sessions/sessions.wxss`](../miniprogram/pages/sessions/sessions.wxss) | 大标题统一为 Display、新建按钮、操作 chip、空状态入口接入令牌 |
| [`pages/memories/memories.wxss`](../miniprogram/pages/memories/memories.wxss) | 全部字面字号/色值接入令牌；删除废弃 `.empty-icon` |
| [`pages/practice/practice.wxss`](../miniprogram/pages/practice/practice.wxss) | 清除整页字面色值，全部接入令牌（含遮罩、品牌投影） |
| [`components/crisis-card/crisis-card.wxss`](../miniprogram/components/crisis-card/crisis-card.wxss) | 字面字号对齐 6 档；色相微暖 + 圆角统一；保留警示强度 |
| [`pages/logs/logs.js`](../miniprogram/pages/logs/logs.js) | 移除情绪色字面值与情绪 emoji，只输出 `colorClass` / `label`；新增空状态入口 `goCheckin` |
| [`pages/index/index.js`](../miniprogram/pages/index/index.js) | 每日一句改为本地文案池按日轮换（14 条，无网络请求）；情绪五档删除 emoji 字段；问候语去「同学」；备注字数提示改为接近上限才出现 |
| [`pages/index/index.wxml`](../miniprogram/pages/index/index.wxml) | hero 副标题改「想说点什么的时候，我都在」；连续记录统一为「🔥 连续记录 N 天」；备注占位去掉字数与「可选」括号 |
| [`pages/chat/chat.wxml`](../miniprogram/pages/chat/chat.wxml) | 删除常驻「0/2000」，改为接近上限时显示「还能写 N 字」 |
| [`pages/chat/chat.js`](../miniprogram/pages/chat/chat.js) | 新增 `countHint()`（1800 字阈值），移除常驻 `maxLen` 字段 |
| [`pages/logs/logs.wxml`](../miniprogram/pages/logs/logs.wxml) | 图例去掉实现细节括号，改为「近 7 天的情绪起伏」；连续记录与「编辑今天的备注」语气改顺 |
| [`pages/mine/mine.js`](../miniprogram/pages/mine/mine.js) | 默认昵称「你」、缺省头像字「屿」，不再出现「同学」 |
| [`pages/practice/practice.js`](../miniprogram/pages/practice/practice.js) | 完成提示改「做完了，现在感觉怎么样」（邀请觉察而非夸奖） |
| [`utils/api.js`](../miniprogram/utils/api.js) | 新增 `SESSION_CONCURRENCY_LIMIT = 5`（与后端 `config.session_concurrency_limit` 对齐） |

> P0 仅调整样式值与文案，WXML 结构变化限于空状态块（删除 `.empty-emoji` / `.empty-icon`，新增 `.empty-action`）。P1-1 起情绪五档与时间线标记的 WXML 由 emoji 文本改为 `.emo-glyph` 色点，样式统一来自 `styles/emotion.wxss`。P0-5 文案批次（称呼、字数提示、日志图例、emoji 文案语气）只改字符串与条件渲染，不动页面结构。

---

## 十、图标资产

图标全部由代码绘制（`tools/gen_icons.py`，Pillow），不引入外部素材、图标库或付费字体；改形只改脚本里的坐标，不手工修图，避免出现无法复现的二进制资产。

### 10.1 目录与命名

| 路径 | 用途 |
|---|---|
| `miniprogram/assets/tabbar/{home,chat,logs,mine}.png` | TabBar 常态（暖灰） |
| `miniprogram/assets/tabbar/{home,chat,logs,mine}-active.png` | TabBar 选中（屿青） |
| `miniprogram/assets/app-icon-144.png` | 小程序头像 / 资料页 |
| `miniprogram/assets/app-icon-512.png` | 分享卡片、商店素材备用 |

命名规则：`<语义>[-active].png`，语义与 `app.json` 的 pagePath 一一对应（index→home、chat→chat、logs→logs、mine→mine）。

### 10.2 规格

| 项 | TabBar 图标 | 应用图标 |
|---|---|---|
| 尺寸 | 81×81 px | 144×144 / 512×512 px |
| 色彩模式 | RGBA，透明底 | RGBA，圆角方形自带遮罩（半径 22.5%） |
| 体积 | 1.7–3.2 KB（上限 40 KB） | 7.7 KB / 27.5 KB |
| 线宽 | 统一 5.6 px（81 画布坐标），圆头端点、圆角转折 | — |
| 实体占比 | 高度 40–42 px（约画布 50%），四枚并排等重 | 岛体占宽约 80% |

### 10.3 两套状态与配色

| 状态 | 颜色 | 令牌 | 出现位置 |
|---|---|---|---|
| 常态 | `#7A736B` | `--text-3` | `tabBar.color`、`iconPath` |
| 选中 | `#3E7A69` | `--brand` | `tabBar.selectedColor`、`selectedIconPath` |
| 底 | `#FDFCFA` | `--surface-warm` | `tabBar.backgroundColor` |

> TabBar 的配色只能写在 `app.json`，WXSS 的 `page` 变量拿不到原生 TabBar。三处色值必须与上表手工保持一致，改令牌时同步改 `app.json`。

四个图标的语义：首页＝屋脊 + 拱门；对话＝气泡 + 三个呼吸点；情绪日志＝纸页 + 三行字；我的＝头 + 圆肩线。

### 10.4 生成方式（可复现）

```bash
python3 tools/gen_icons.py
```

依赖 `Pillow`。脚本以 8 倍超采样绘制，再用 LANCZOS 缩到目标尺寸，避免 81 px 下的锯齿；运行末尾会打印每个文件的尺寸与体积。应用图标为深屿青渐变底 + 奶油色双峰岛脊 + 水面倒影 + 暖沙圆点，不使用纯白底。

---

## 十一、微信开发者工具自检清单

小程序无法无头渲染，请在开发者工具逐项确认：

- [ ] 导航栏：暖米白底 + 黑色标题清晰可读
- [ ] tabBar：四个图标并排视觉重量一致；选中屿青与未选中暖灰对比清楚，图标不糊边
- [ ] 对话页：用户气泡（屿青底白字）与 AI 气泡（白底）层次分明；头像渐变上"小屿"可读
- [ ] 首页：情绪项未选/已选对比；连续打卡暖沙徽章
- [ ] 首页情绪五档色点：平静（实心无描边）/ 还行（细描边浅核）/ 低落（空心）/ 焦虑（外环）/ 烦躁（粗描边）五档一眼可区分
- [ ] 首页已打卡卡片：44rpx 色点与「平静 · 强度 2/10」文字对齐、不挤压换行
- [ ] 危机卡片：high 红 / mid 琥珀一眼可区分；"拨打"按钮醒目
- [ ] 情绪日志：柱状图屿青渐变；筛选 chip 选中态
- [ ] 情绪日志时间线：72rpx 徽章内 28rpx 色点是否清晰；焦虑外环在小尺寸下是否过密；文字标签颜色与色点语义一致
- [ ] 文案口径：全站无「同学」；对话输入默认不显示字数，输入到 1800 字后才出现「还能写 N 字」；打卡备注剩余 40 字内才提示
- [ ] 合规：所有页面文案无「诊断 / 治疗 / 药物 / 治愈」表述；危机卡片与免责声明文案与改动前一致或更清楚
- [ ] 空状态 / 禁用态：禁用色 `#BFD1C9` 观感合适
- [ ] 真机预览：不同屏幕下圆角与阴影观感一致
