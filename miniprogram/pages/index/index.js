// pages/index/index.js —— 首页：按时段问候 + 每日一句 + 记忆型问候 + 五档情绪打卡
const api = require('../../utils/api')

// 情绪五档：key 即后端打卡词汇（calm/ok/low/anxious/irritable），渲染于 styles/emotion.wxss
const MOODS = [
  { key: 'calm', label: '平静' },
  { key: 'ok', label: '还行' },
  { key: 'low', label: '低落' },
  { key: 'anxious', label: '焦虑' },
  { key: 'irritable', label: '烦躁' },
]

// 每日一句：本地维护一组合规文案（不诊断、不治疗承诺、不鸡血），按日期轮换，不发网络请求
const DAILY_QUOTES = [
  '情绪没有好坏，它们都只是来送信的。',
  '慢慢来，事情一件一件做。',
  '累了可以停一下，这不叫放弃。',
  '今天的你，已经撑过很多事了。',
  '睡不着的时候，先让呼吸慢下来。',
  '不必马上变好，先好好待着就行。',
  '把担心写下来，它会轻一点。',
  '你不需要每时每刻都很努力。',
  '难过有它的时间，急不来。',
  '先照顾好这十分钟，剩下的一会儿再说。',
  '和人说说，或者先和这里说说。',
  '允许今天普通一点。',
  '心里的天气，也会慢慢换的。',
  '来都来了，坐一会儿再走。',
]

// 按年内第几天取模轮换，同一天内稳定不变
function todayQuote() {
  const now = new Date()
  const yearStart = new Date(now.getFullYear(), 0, 0)
  const dayOfYear = Math.floor((now - yearStart) / 86400000)
  return DAILY_QUOTES[dayOfYear % DAILY_QUOTES.length]
}

const MOOD_META = {
  calm: { text: '平静' },
  ok: { text: '还行' },
  low: { text: '低落' },
  anxious: { text: '焦虑' },
  irritable: { text: '烦躁' },
}

function decorateCheckin(c) {
  if (!c) return null
  const meta = MOOD_META[c.mood] || { text: c.mood }
  return { ...c, moodText: meta.text }
}

Page({
  data: {
    greeting: '',
    dailyQuote: todayQuote(),
    memoryGreeting: '',
    streak: 0,
    moods: MOODS,
    selected: '',
    note: '',
    showNoteCount: false,
    noteLeft: 200,
    submitting: false,
    todayCheckin: null, // {mood, intensity, note, date} 或 null
  },

  onShow() {
    // 跨零点回到前台时刷新每日一句（同一天内取值稳定）
    const quote = todayQuote()
    if (quote !== this.data.dailyQuote) this.setData({ dailyQuote: quote })
    api
      .ensureLogin()
      // B-3：以服务端 consent_at 为准，未同意时不请求业务接口，直接进同意流程
      .then(() => api.get('/api/v1/users/me'))
      .then((me) => {
        api.setConsented(!!me.consented)
        if (!me.consented) {
          this.maybeShowConsent()
          return null
        }
        return this.loadHome(me)
      })
      .catch((err) => {
        wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' })
      })
  },

  // P4/P5 隐私单独同意：未同意时弹窗（不写持久标记，每次冷启动都会重新征询）；
  // 同意成功后才写本地状态并放行，拒绝则停在首页，「我的」页保留重新同意入口
  maybeShowConsent() {
    if (this._consentPrompted) return
    if (api.getLocalUser().consented) return
    this._consentPrompted = true
    wx.showModal({
      title: '隐私政策与使用同意',
      content:
        '「心屿」会记录你的对话内容、情绪与打卡数据，仅用于陪伴与自我觉察；' +
        '对话内容采用加密存储，你可随时导出或删除全部数据。' +
        '本产品为校园心理陪伴工具，不提供医疗诊断。' +
        '是否同意《隐私政策》并开始使用？',
      confirmText: '同意并继续',
      cancelText: '暂不同意',
      success: (res) => {
        this._consentPrompted = false
        if (!res.confirm) {
          wx.showToast({ title: '同意后才能记录与对话，可稍后在「我的」页开启', icon: 'none' })
          return
        }
        api
          .post('/api/v1/users/me/consent', { agree: true, policy_version: '1.0' })
          .then(() => {
            api.setConsented(true)
            return this.loadHome()
          })
          .catch(() => {
            wx.showToast({ title: '同意保存失败，请稍后重试', icon: 'none' })
          })
      },
    })
  },

  // 入口门：未同意不进入对话 / 不写打卡数据（服务端同样会拦 2007）
  requireConsent() {
    if (api.getLocalUser().consented) return true
    this.maybeShowConsent()
    return false
  },

  loadHome(me) {
    const greeting = this.timeGreeting()
    this.setData({ greeting })
    // 并行拉取：用户信息（连续天数 + 记忆型问候）+ 今日打卡
    Promise.all([
      me ? Promise.resolve(me) : api.get('/api/v1/users/me'),
      api.get('/api/v1/emotion/checkins/today'),
    ])
      .then(([user, today]) => {
        api.setConsented(!!user.consented)
        this.setData({
          streak: user.checkin_streak || 0,
          memoryGreeting: user.memory_greeting || '',
          todayCheckin: decorateCheckin(today),
        })
      })
      .catch((err) => {
        if (err && err.code === 2007) {
          this.maybeShowConsent()
          return
        }
        wx.showToast({ title: '加载失败，请稍后重试', icon: 'none' })
      })
  },

  // 按时段三档问候（上午 / 下午 / 深夜）；不叫「同学」，直接说话
  timeGreeting() {
    const h = new Date().getHours()
    if (h >= 5 && h < 12) return '早，今天也来了'
    if (h >= 12 && h < 18) return '下午好，今天也来了'
    if (h >= 18 && h < 23) return '晚上好，今天也来了'
    return '夜深了，还没睡呀'
  },

  selectMood(e) {
    const key = e.currentTarget.dataset.key
    this.setData({ selected: key })
  },

  onNoteInput(e) {
    const v = e.detail.value
    const left = 200 - v.length
    // 只在剩余 40 字以内提示，避免输入时一直盯着计数
    this.setData({ note: v, showNoteCount: left <= 40, noteLeft: left })
  },

  submitCheckin() {
    if (!this.requireConsent()) return
    const mood = this.data.selected
    if (!mood || this.data.submitting) return
    if (this.data.note.length > 200) {
      wx.showToast({ title: '备注最多 200 字', icon: 'none' })
      return
    }
    this.setData({ submitting: true })
    api
      .post('/api/v1/emotion/checkins', { mood, note: this.data.note || null })
      .then((d) => {
        this.setData({
          todayCheckin: decorateCheckin({
            mood: d.mood,
            intensity: d.intensity,
            note: d.note,
            date: d.date,
          }),
          streak: d.streak,
          selected: '',
          note: '',
          showNoteCount: false,
          noteLeft: 200,
          submitting: false,
        })
        wx.showToast({ title: d.updated ? '已更新今天的记录' : '已记录', icon: 'success' })
      })
      .catch((err) => {
        this.setData({ submitting: false })
        wx.showToast({ title: (err && err.message) || '打卡失败', icon: 'none' })
      })
  },

  startChat() {
    if (!this.requireConsent()) return
    // 对话页是 tab，reLaunch 可带全新会话（onLoad 自动新建）
    wx.reLaunch({ url: '/pages/chat/chat' })
  },

  // 练习卡片（V4）：非 tab 页，用 navigateTo 保留首页栈
  goPractice() {
    wx.navigateTo({ url: '/pages/practice/practice' })
  },
})
