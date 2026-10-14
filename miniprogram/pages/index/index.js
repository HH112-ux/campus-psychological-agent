// pages/index/index.js —— 首页：按时段问候 + 每日一句 + 记忆型问候 + 五档情绪打卡
const api = require('../../utils/api')

const MOODS = [
  { key: 'calm', emoji: '😌', label: '平静' },
  { key: 'ok', emoji: '🙂', label: '还行' },
  { key: 'low', emoji: '😔', label: '低落' },
  { key: 'anxious', emoji: '😰', label: '焦虑' },
  { key: 'irritable', emoji: '😠', label: '烦躁' },
]

const DAILY_QUOTE = '情绪没有好坏，它们都只是来送信的。'

const MOOD_META = {
  calm: { emoji: '😌', text: '平静' },
  ok: { emoji: '🙂', text: '还行' },
  low: { emoji: '😔', text: '低落' },
  anxious: { emoji: '😰', text: '焦虑' },
  irritable: { emoji: '😠', text: '烦躁' },
}

function decorateCheckin(c) {
  if (!c) return null
  const meta = MOOD_META[c.mood] || { emoji: '🙂', text: c.mood }
  return { ...c, moodEmoji: meta.emoji, moodText: meta.text }
}

Page({
  data: {
    greeting: '',
    dailyQuote: DAILY_QUOTE,
    memoryGreeting: '',
    streak: 0,
    moods: MOODS,
    selected: '',
    note: '',
    submitting: false,
    todayCheckin: null, // {mood, intensity, note, date} 或 null
  },

  onShow() {
    api
      .ensureLogin()
      .then(() => {
        this.maybeShowConsent()
        return this.loadHome()
      })
      .catch((err) => {
        wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' })
      })
  },

  // P4/P5 隐私单独同意：首次进入且未同意时弹窗；本地标记防反复打扰，
  // 「我的」页保留重新同意入口
  maybeShowConsent() {
    const u = api.getLocalUser()
    if (u.consented || wx.getStorageSync('xinyu_consent_prompted')) return
    wx.setStorageSync('xinyu_consent_prompted', true)
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
        if (!res.confirm) {
          wx.showToast({ title: '同意后可开始使用，稍后可在「我的」页开启', icon: 'none' })
          return
        }
        api
          .post('/api/v1/users/me/consent', { agree: true, policy_version: '1.0' })
          .then(() => {
            const nu = api.getLocalUser()
            nu.consented = true
            wx.setStorageSync('xinyu_user', nu)
          })
          .catch(() => {
            wx.showToast({ title: '同意保存失败，请稍后重试', icon: 'none' })
          })
      },
    })
  },

  loadHome() {
    const greeting = this.timeGreeting()
    this.setData({ greeting })
    // 并行拉取：用户信息（连续天数 + 记忆型问候）+ 今日打卡
    Promise.all([
      api.get('/api/v1/users/me'),
      api.get('/api/v1/emotion/checkins/today'),
    ])
      .then(([me, today]) => {
        this.setData({
          streak: me.checkin_streak || 0,
          memoryGreeting: me.memory_greeting || '',
          todayCheckin: decorateCheckin(today),
        })
      })
      .catch(() => {
        wx.showToast({ title: '加载失败，请稍后重试', icon: 'none' })
      })
  },

  // 按时段三档问候（上午 / 下午 / 深夜）
  timeGreeting() {
    const h = new Date().getHours()
    if (h >= 5 && h < 12) return '早上好，同学'
    if (h >= 12 && h < 18) return '下午好，同学'
    if (h >= 18 && h < 23) return '晚上好，同学'
    return '夜深了，同学'
  },

  selectMood(e) {
    const key = e.currentTarget.dataset.key
    this.setData({ selected: key })
  },

  onNoteInput(e) {
    this.setData({ note: e.detail.value })
  },

  submitCheckin() {
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
    // 对话页是 tab，reLaunch 可带全新会话（onLoad 自动新建）
    wx.reLaunch({ url: '/pages/chat/chat' })
  },
})
