// pages/mine/mine.js —— 我的：个人区 + 历史会话 + 求助热线 + 免责声明
const api = require('../../utils/api')

const DISCLAIMER =
  '心屿是情绪陪伴与记录工具，不能替代专业心理咨询或医疗诊断。' +
  '如果你正处于危机之中，请立即拨打页内求助热线。'

Page({
  data: {
    nickname: '同学',
    avatarChar: '同',
    consented: false,
    version: '',
    resources: [], // 求助热线（公开接口，无需登录）
  },

  onShow() {
    const app = getApp()
    this.setData({ version: app.globalData.version })

    // 公开求助资源（app.js 已缓存，这里兜底拉取一次）
    const cached = app.globalData.crisisResources || []
    if (cached.length) {
      this.setData({ resources: cached })
    } else {
      api.rawRequest({ url: '/api/v1/crisis/resources', method: 'GET', auth: false }).then(
        (d) => this.setData({ resources: d.resources || [] }),
        () => {}
      )
    }

    api
      .ensureLogin()
      .then(() => api.get('/api/v1/users/me'))
      .then((me) => {
        this.setData({
          nickname: me.nickname || '同学',
          avatarChar: (me.nickname || '同').slice(0, 1),
          consented: !!me.consented,
        })
      })
      .catch(() => {})
  },

  openSessions() {
    wx.navigateTo({ url: '/pages/sessions/sessions' })
  },

  callHotline(e) {
    const phone = e.currentTarget.dataset.phone
    if (phone) wx.makePhoneCall({ phoneNumber: phone })
  },

  showDisclaimer() {
    wx.showModal({
      title: '关于与免责声明',
      content: DISCLAIMER,
      showCancel: false,
      confirmText: '我知道了',
    })
  },
})
