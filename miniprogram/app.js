// app.js —— 心屿小程序入口（P0 占位）
App({
  globalData: {
    // P0 本地后端地址；真机/正式环境需替换为已备案的 HTTPS 域名
    apiBase: 'http://127.0.0.1:8000',
    version: '0.1.0',
  },

  onLaunch() {
    // P0：仅打印版本，确认小程序工程可正常启动
    console.log('[心屿] 小程序启动，版本', this.globalData.version)
  },
})
