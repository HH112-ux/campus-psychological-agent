// app.js —— 心屿小程序入口（P1）
const api = require('./utils/api')

App({
  globalData: {
    // 本地后端地址；真机/正式环境需替换为已备案的 HTTPS 域名
    apiBase: 'http://127.0.0.1:8000',
    version: '0.2.0',
    crisisResources: [], // 公开求助热线缓存（高危卡片重进会话时使用）
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
