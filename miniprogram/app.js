// app.js —— 心屿小程序入口（P3）
const api = require('./utils/api')
const config = require('./config')

App({
  globalData: {
    // 发布地址统一在 config.js 配置（按 envVersion 自动切换），此处不再硬编码域名
    apiBase: config.apiBase,
    version: '0.3.0',
    crisisResources: [], // 公开求助热线缓存（高危卡片重进会话时使用）
    // 主动关怀（V3）订阅消息模板 ID：在微信公众平台申请后填入；
    // 留空时前端不发起 requestSubscribeMessage（与后端 WX_SUBSCRIBE_TEMPLATE_ID 保持一致）
    subscribeTemplateId: '',
  },

  onLaunch() {
    // 预热静默登录（失败不阻塞，页面内会再次 ensureLogin）
    api.ensureLogin().catch(() => {})

    // 拉取公开求助资源（无需鉴权）
    api.rawRequest({ url: '/api/v1/crisis/resources', method: 'GET', auth: false }).then(
      (d) => {
        this.globalData.crisisResources = d.resources || []
      },
      () => {}
    )
  },
})
