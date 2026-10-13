// pages/sessions/sessions.js —— 会话列表（首页）
const api = require('../../utils/api')

Page({
  data: {
    items: [],
    loading: true,
    loaded: false,
  },

  onShow() {
    api
      .ensureLogin()
      .then(() => this.loadList())
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' })
      })
  },

  loadList() {
    this.setData({ loading: true })
    api
      .get('/api/v1/sessions?page=1&page_size=20')
      .then((d) => {
        const items = (d.items || []).map((s) => ({
          ...s,
          timeText: this.fmtTime(s.last_msg_at),
        }))
        this.setData({ items, loading: false, loaded: true })
      })
      .catch((err) => {
        this.setData({ loading: false, loaded: true })
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
  },

  fmtTime(iso) {
    if (!iso) return ''
    const t = new Date(iso)
    if (isNaN(t.getTime())) return ''
    const now = new Date()
    const sameDay = t.toDateString() === now.toDateString()
    const pad = (n) => String(n).padStart(2, '0')
    if (sameDay) return `${pad(t.getHours())}:${pad(t.getMinutes())}`
    return `${t.getMonth() + 1}/${t.getDate()}`
  },

  newChat() {
    if (this.data.items.length >= 3) {
      wx.showModal({
        title: '会话数量已达上限',
        content: '最多保留 3 个进行中的对话，请先删除一个旧会话。',
        showCancel: false,
      })
      return
    }
    wx.navigateTo({ url: '/pages/chat/chat' })
  },

  openChat(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/chat/chat?session_id=${id}` })
  },

  rename(e) {
    const { id, title } = e.currentTarget.dataset
    wx.showModal({
      title: '重命名会话',
      editable: true,
      placeholderText: '给这段对话起个名字',
      content: title,
      success: (res) => {
        if (!res.confirm) return
        const name = (res.content || '').trim()
        if (!name) return
        api.patch(`/api/v1/sessions/${id}`, { title: name.slice(0, 20) }).then(() => {
          wx.showToast({ title: '已重命名', icon: 'success' })
          this.loadList()
        })
      },
    })
  },

  remove(e) {
    const id = e.currentTarget.dataset.id
    wx.showModal({
      title: '删除这段对话？',
      content: '删除后对话内容将无法恢复。',
      confirmText: '删除',
      confirmColor: '#e23b2a',
      success: (res) => {
        if (!res.confirm) return
        api.del(`/api/v1/sessions/${id}`).then(() => {
          wx.showToast({ title: '已删除', icon: 'success' })
          this.loadList()
        })
      },
    })
  },

  openDiagnose() {
    wx.navigateTo({ url: '/pages/index/index' })
  },
})
