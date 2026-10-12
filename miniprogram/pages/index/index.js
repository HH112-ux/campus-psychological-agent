// pages/index/index.js —— P0 占位首页
const app = getApp()

Page({
  data: {
    version: '',
    healthText: '未检测',
    healthDesc: '点击按钮检测本地后端 /health',
    checking: false,
  },

  onLoad() {
    this.setData({ version: app.globalData.version })
  },

  // 调用后端 /health，验证小程序 → FastAPI 链路（P0 验收项）
  checkHealth() {
    this.setData({ checking: true, healthText: '检测中…' })
    wx.request({
      url: `${app.globalData.apiBase}/health`,
      method: 'GET',
      timeout: 5000,
      success: (res) => {
        const body = res.data || {}
        if (res.statusCode === 200 && body.code === 0) {
          const db = body.data && body.data.db
          this.setData({
            healthText: '连接正常',
            healthDesc: `服务 ${body.data.service} v${body.data.version}，数据库：${db}`,
          })
        } else {
          this.setData({
            healthText: '返回异常',
            healthDesc: `HTTP ${res.statusCode}`,
          })
        }
      },
      fail: (err) => {
        this.setData({
          healthText: '连接失败',
          healthDesc: '请确认后端已启动（uvicorn 8000）且开发者工具已勾选“不校验合法域名”',
        })
        console.error('[心屿] /health 请求失败', err)
      },
      complete: () => {
        this.setData({ checking: false })
      },
    })
  },
})
