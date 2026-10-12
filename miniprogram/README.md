# 心屿 · 微信小程序（P0 占位工程）

P0 阶段只提供一个可编译启动的占位首页，用于验证小程序工程链路；正式页面（对话、情绪记录等）从 P2 起开发。

## 技术栈

微信小程序原生框架（WXML + WXSS + JS），不引入第三方框架。

## 目录结构

```
miniprogram/
├── app.js / app.json / app.wxss   # 小程序入口与全局配置
├── project.config.json            # 开发者工具项目配置
├── sitemap.json
└── pages/index/                   # P0 占位首页（含 /health 连通性检测）
```

## 运行方式

1. 下载并打开「微信开发者工具」（稳定版）。
2. 选择「导入项目」，目录指向本 `miniprogram/` 文件夹。
3. AppID 暂无时选择「测试号 / 游客模式」（工程内已用 `touristappid` 占位，正式上线前替换为注册的 AppID）。
4. 后端联调：先启动后端（见 `../backend/README.md`，监听 127.0.0.1:8000）；
   开发阶段已在 `project.config.json` 关闭域名校验（`urlCheck: false`），
   点击首页「检测 /health」按钮应显示「连接正常，数据库：connected」。

## P0 验收标准

- 工程可在微信开发者工具中正常编译，显示占位首页；
- 点击「检测 /health」可打通小程序 → FastAPI 链路。

## 注意事项

- 正式提审前必须：替换真实 AppID、配置 HTTPS 合法域名（后端需备案域名 + TLS）、重新开启域名校验。
- 小程序内不展示、不落盘任何超出必要范围的心理敏感信息（对齐 SECURITY.md）。
