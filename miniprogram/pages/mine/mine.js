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

  // P4/P5：隐私同意入口（未同意时可在此重新同意）
  showConsent() {
    if (this.data.consented) {
      wx.showToast({ title: '你已同意隐私政策', icon: 'none' })
      return
    }
    wx.showModal({
      title: '隐私政策与使用同意',
      content:
        '「心屿」会记录你的对话内容、情绪与打卡数据，仅用于陪伴与自我觉察；' +
        '对话内容采用加密存储，你可随时导出或删除全部数据。' +
        '本产品为校园心理陪伴工具，不提供医疗诊断。',
      confirmText: '同意',
      cancelText: '再想想',
      success: (res) => {
        if (!res.confirm) return
        api
          .post('/api/v1/users/me/consent', { agree: true, policy_version: '1.0' })
          .then(() => {
            const u = api.getLocalUser()
            u.consented = true
            wx.setStorageSync('xinyu_user', u)
            this.setData({ consented: true })
            wx.showToast({ title: '已记录同意', icon: 'none' })
          })
          .catch(() => {
            wx.showToast({ title: '保存失败，请稍后重试', icon: 'none' })
          })
      },
    })
  },
})
