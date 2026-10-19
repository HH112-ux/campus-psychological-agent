// pages/logs/logs.js —— 情绪日志：7 天趋势 + 时间线（对话 + 打卡合并）
const api = require('../../utils/api')

const EMOTION_META = {
  anxious: { emoji: '😰', text: '焦虑', color: '#e06666' },
  depressed: { emoji: '😔', text: '低落', color: '#6b7fa8' },
  calm: { emoji: '🙂', text: '平静', color: '#6fae7f' },
  ok: { emoji: '🙂', text: '还行', color: '#6fae7f' },
  angry: { emoji: '😠', text: '烦躁', color: '#e0913e' },
  other: { emoji: '🌿', text: '其他', color: '#7a736b' },
}

const FILTERS = [
  { key: '', label: '全部' },
  { key: 'anxious', label: '焦虑' },
  { key: 'depressed', label: '低落' },
  { key: 'calm', label: '平静' },
  { key: 'ok', label: '还行' },
  { key: 'angry', label: '烦躁' },
  { key: 'other', label: '其他' },
]

const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六']

Page({
  data: {
    filters: FILTERS,
    filter: '',
    streak: 0,
    avgIntensity: null,
    trendDesc: '',
    dominantText: '',
    insight: null, // 本周小结（V2 周报洞察，has_data 为 false 时不展示）
    bars: [], // {date, label, height, dominant, count, avg}
    items: [],
    page: 0,
    hasMore: true,
    loading: false,
  },

  onShow() {
    api
      .ensureLogin()
      .then(() => this.refresh())
      .catch((err) => {
        wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' })
      })
  },

  refresh() {
    this.setData({ items: [], page: 0, hasMore: true, loading: true })
    Promise.all([this.loadTrend(), this.loadInsight(), this.loadRecords(true)])
      .catch(() => wx.showToast({ title: '加载失败，请稍后重试', icon: 'none' }))
      .finally(() => this.setData({ loading: false }))
  },

  loadInsight() {
    // V2 周报洞察：服务端已生成描述性小结文案，小程序只渲染
    return api
      .get('/api/v1/emotion/weekly-insight?days=7')
      .then((d) => this.setData({ insight: d }))
      .catch(() => {})
  },

  loadTrend() {
    return api
      .get('/api/v1/users/me')
      .then((me) => this.setData({ streak: me.checkin_streak || 0 }))
      .catch(() => {})
      .then(() => api.get('/api/v1/emotion/trends?days=7&granularity=day'))
      .then((d) => this.renderTrend(d))
  },

  renderTrend(d) {
    const avg = d.avg_intensity
    const prev = d.prev_avg_intensity
    let desc = '近 7 天暂无情绪记录，聊聊天或打个卡就有了'
    if (avg !== null) {
      if (prev === null) {
        desc = `近 7 天平均强度 ${avg}`
      } else {
        const diff = +(avg - prev).toFixed(1)
        const word = diff > 0 ? '高了' : diff < 0 ? '低了' : '持平'
        const val = diff === 0 ? '' : ` ${Math.abs(diff)}`
        desc = `近 7 天平均强度 ${avg}，比上周${word}${val}`
      }
    }
    const dom = d.dominant_emotion
    const domMeta = dom && EMOTION_META[dom.type]
    const dominantText = dom ? `本周以「${domMeta ? domMeta.text : dom.type}」为主` : ''

    // 7 天柱状：无记录高度为 0，不补 0
    const bars = (d.points || []).map((p) => {
      const dateObj = new Date(`${p.date}T00:00:00+08:00`)
      const height = p.avg_intensity !== null ? Math.max(6, Math.round((p.avg_intensity / 10) * 100)) : 2
      return {
        date: p.date,
        label: WEEKDAY[dateObj.getDay()],
        height,
        avg: p.avg_intensity,
        count: p.count,
        dominant: p.dominant,
      }
    })
    this.setData({ avgIntensity: avg, trendDesc: desc, dominantText, bars })
  },

  loadRecords(reset) {
    if (!reset && (!this.data.hasMore || this.data.loading)) return Promise.resolve()
    const page = reset ? 1 : this.data.page + 1
    const query = `/api/v1/emotion/records?page=${page}&page_size=20`
      + (this.data.filter ? `&emotion=${this.data.filter}` : '')
    return api.get(query).then((d) => {
      const todayStr = new Date().toISOString().slice(0, 10)
      const decorated = (d.items || []).map((it) => {
        const meta = EMOTION_META[it.emotion] || { emoji: '🌿', text: it.emotion, color: '#7a736b' }
        const canEditNote = it.source === 'checkin' && (it.created_at || '').slice(0, 10) === todayStr
        return { ...it, emoji: meta.emoji, label: meta.text, color: meta.color, timeText: this.fmtTime(it.created_at), canEditNote }
      })
      this.setData({
        items: reset ? decorated : this.data.items.concat(decorated),
        page,
        hasMore: (d.items || []).length >= d.page_size,
      })
    })
  },

  fmtTime(iso) {
    if (!iso) return ''
    const t = new Date(iso)
    if (isNaN(t.getTime())) return ''
    const pad = (n) => String(n).padStart(2, '0')
    return `${t.getMonth() + 1}月${t.getDate()}日 ${pad(t.getHours())}:${pad(t.getMinutes())}`
  },

  onReachBottom() {
    this.loadRecords(false)
  },

  onFilterTap(e) {
    const key = e.currentTarget.dataset.key
    if (key === this.data.filter) return
    this.setData({ filter: key, items: [], page: 0, hasMore: true, loading: true })
    this.loadRecords(true)
      .catch(() => wx.showToast({ title: '加载失败', icon: 'none' }))
      .finally(() => this.setData({ loading: false }))
  },

  // 时间线条目交互（P2/P3 spec）：对话来源 → 定位到来源会话；当日打卡 → 编辑备注
  onItemTap(e) {
    const { id } = e.currentTarget.dataset
    const item = this.data.items.find((it) => it.record_id === id)
    if (!item) return
    if (item.source === 'message') {
      if (item.session_id) {
        wx.reLaunch({ url: `/pages/chat/chat?session_id=${item.session_id}` })
      } else {
        wx.showToast({ title: '对话已删除，仅保留记录', icon: 'none' })
      }
    } else if (item.canEditNote) {
      this.editCheckinNote(item)
    }
  },

  editCheckinNote(item) {
    wx.showModal({
      title: '补充今天的备注',
      editable: true,
      placeholderText: '记录此刻的心情细节（200 字内）',
      content: item.note || '',
      success: (res) => {
        if (!res.confirm) return
        const note = (res.content || '').trim().slice(0, 200)
        api
          .post('/api/v1/emotion/checkins', { mood: item.mood, note: note || null })
          .then(() => {
            wx.showToast({ title: '已更新', icon: 'success' })
            this.refresh()
          })
          .catch((err) => wx.showToast({ title: (err && err.message) || '更新失败', icon: 'none' }))
      },
    })
  },
})
