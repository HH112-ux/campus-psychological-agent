// pages/memories/memories.js —— 长期记忆（V6）：查看 / 删除单条 / 清空全部（PIPL 行权）
const api = require('../../utils/api')

const KIND_ORDER = ['person', 'event', 'preference', 'trigger']
const KIND_LABELS = {
  person: '人物',
  event: '事件',
  preference: '偏好',
  trigger: '情绪诱因',
}

Page({
  data: {
    loading: true,
    total: 0,
    groups: [], // [{ kind, label, items: [{ memory_id, content }] }]
  },

  onShow() {
    this.load()
  },

  load() {
    this.setData({ loading: true })
    api
      .ensureLogin()
      .then(() => api.get('/api/v1/memories'))
      .then((d) => {
        const items = d.memories || []
        const groups = KIND_ORDER.map((kind) => ({
          kind,
          label: KIND_LABELS[kind],
          items: items.filter((m) => m.kind === kind),
        })).filter((g) => g.items.length > 0)
        this.setData({ groups, total: d.total || items.length, loading: false })
      })
      .catch(() => {
        this.setData({ loading: false })
        wx.showToast({ title: '加载失败，请稍后重试', icon: 'none' })
      })
  },

  // 删除单条（确认后调 DELETE /api/v1/memories/{id}）
  removeOne(e) {
    const { id, content } = e.currentTarget.dataset
    if (!id) return
    wx.showModal({
      title: '删除这条记忆',
      content: `「${content}」\n删除后我不会再记得它。`,
      confirmText: '删除',
      confirmColor: '#c1342a',
      success: (res) => {
        if (!res.confirm) return
        api
          .del(`/api/v1/memories/${id}`)
          .then(() => {
            wx.showToast({ title: '已删除', icon: 'none' })
            this.load()
          })
          .catch(() => wx.showToast({ title: '删除失败，请稍后重试', icon: 'none' }))
      },
    })
  },

  // 清空全部（二次确认，防止误触）
  clearAll() {
    if (!this.data.total) return
    wx.showModal({
      title: '清空全部长期记忆',
      content: `将删除全部 ${this.data.total} 条记忆，删除后不可恢复。`,
      confirmText: '继续',
      confirmColor: '#c1342a',
      success: (res) => {
        if (!res.confirm) return
        wx.showModal({
          title: '再次确认',
          content: '清空后我不会再记得这些内容，确定全部删除吗？',
          confirmText: '全部删除',
          confirmColor: '#c1342a',
          success: (res2) => {
            if (!res2.confirm) return
            api
              .del('/api/v1/memories')
              .then(() => {
                wx.showToast({ title: '已清空', icon: 'none' })
                this.load()
              })
              .catch(() => wx.showToast({ title: '操作失败，请稍后重试', icon: 'none' }))
          },
        })
      },
    })
  },
})
