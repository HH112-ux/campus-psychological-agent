// pages/chat/chat.js —— 对话页：SSE 流式 + 非流式降级 + 危机卡片
const api = require('../../utils/api')
const { openSse } = require('../../utils/sse')

const MAX_LEN = 2000

// 情绪角标展示映射（P3：对话页本轮识别）
const EMOTION_META = {
  anxious: { text: '焦虑', colorClass: 'emotion-badge--red' },
  depressed: { text: '低落', colorClass: 'emotion-badge--blue' },
  calm: { text: '平静', colorClass: 'emotion-badge--green' },
  ok: { text: '还行', colorClass: 'emotion-badge--green' },
  angry: { text: '烦躁', colorClass: 'emotion-badge--orange' },
  other: { text: '其他', colorClass: 'emotion-badge--gray' },
}

function decorateEmotion(emo) {
  if (!emo) return null
  const meta = EMOTION_META[emo.type] || { text: emo.type, colorClass: 'emotion-badge--gray' }
  return { ...emo, emotionText: meta.text, colorClass: meta.colorClass }
}

Page({
  data: {
    sessionId: '',
    ready: false, // 会话初始化（登录+建会话/加载历史）完成前不可发送
    messages: [], // {key, role, content, degraded} 或 {key, card:'mid', resources}
    inputValue: '',
    sending: false,
    typing: false,
    highCard: null, // 高危卡片：置顶常驻
    scrollTo: '',
    seq: 0,
    chunkSupported: true,
    maxLen: MAX_LEN,
    canSend: false,
  },

  onLoad(options) {
    this._streamText = ''
    this._sseTask = null
    this.app = getApp()

    api
      .ensureLogin()
      .then(() => this.detectChunk())
      .then(() => {
        if (options && options.session_id) {
          this.setData({ sessionId: options.session_id })
          return this.loadDetail()
        }
        return this.createSession()
      })
      .then(() => {
        // 就绪后同步刷新发送可用态（用户可能已在输入框敲好内容）
        const v = this.data.inputValue
        this.setData({
          ready: true,
          canSend: v.trim().length > 0 && v.length <= MAX_LEN && !this.data.sending,
        })
      })
      .catch((err) => {
        if (err && err.code === 2003) {
          wx.showModal({
            title: '会话数量已达上限',
            content: '最多保留 3 个进行中的对话，请先在列表删除一个旧会话。',
            showCancel: false,
            confirmText: '我知道了',
            success: () => wx.switchTab({ url: '/pages/index/index' }),
          })
        } else {
          wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
        }
      })
  },

  onUnload() {
    if (this._sseTask) {
      try {
        this._sseTask.abort()
      } catch (e) {}
    }
  },

  // 探测基础库是否支持分块接收（用幂等的 /health，不污染对话）
  detectChunk() {
    return new Promise((resolve) => {
      try {
        const task = wx.request({
          url: api.base() + '/health',
          method: 'GET',
          enableChunked: true,
          complete: () => {},
        })
        const ok = task && typeof task.onChunkReceived === 'function'
        this.setData({ chunkSupported: ok })
      } catch (e) {
        this.setData({ chunkSupported: false })
      }
      resolve()
    })
  },

  createSession() {
    return api.post('/api/v1/sessions', {}).then((d) => {
      this.setData({ sessionId: d.session_id })
      wx.setNavigationBarTitle({ title: d.title })
    })
  },

  loadDetail() {
    return api.get(`/api/v1/sessions/${this.data.sessionId}`).then((d) => {
      const msgs = []
      let seq = 0
      d.messages.forEach((m) => {
        msgs.push({
          key: `m${seq++}`,
          role: m.role,
          content: m.content,
          degraded: m.degraded || false,
          emotion: decorateEmotion(m.emotion),
        })
      })
      const patch = { messages: msgs, seq }
      if (d.crisis_high_shown) {
        patch.highCard = { level: 'high', resources: (this.app.globalData.crisisResources || []) }
      }
      this.setData(patch)
      this.scrollToBottom()
    })
  },

  onInput(e) {
    const v = e.detail.value
    this.setData({
      inputValue: v,
      canSend: v.trim().length > 0 && v.length <= MAX_LEN && !this.data.sending && this.data.ready,
    })
  },

  // ---------- 发送 ----------
  send() {
    const content = (this.data.inputValue || '').trim()
    if (!content || this.data.sending) return
    if (content.length > MAX_LEN) {
      wx.showToast({ title: `单次最多 ${MAX_LEN} 字`, icon: 'none' })
      return
    }
    if (!this.data.ready) {
      wx.showToast({ title: '对话正在准备中，请稍候', icon: 'none' })
      return
    }
    if (!this.data.sessionId) {
      wx.showToast({ title: '会话还没准备好，请稍候再试', icon: 'none' })
      return
    }

    // 本地立即展示用户气泡
    const userKey = `m${this.data.seq++}`
    const aiKey = `m${this.data.seq++}`
    this.setData({
      inputValue: '',
      canSend: false,
      sending: true,
      typing: true,
      messages: [
        ...this.data.messages,
        { key: userKey, role: 'user', content },
        { key: aiKey, role: 'assistant', content: '' },
      ],
    })
    this._aiKey = aiKey
    this._streamText = ''
    this.scrollToBottom()

    if (this.data.chunkSupported) {
      this.sendStream(content)
    } else {
      this.sendNonStream(content)
    }
  },

  _aiIndex() {
    return this.data.messages.findIndex((m) => m.key === this._aiKey)
  },

  _patchAi(patch) {
    const idx = this._aiIndex()
    if (idx < 0) return
    const data = {}
    Object.keys(patch).forEach((k) => {
      data[`messages[${idx}].${k}`] = patch[k]
    })
    this.setData(data)
  },

  // 流式
  sendStream(content) {
    const idx = this._aiIndex()
    this._sseTask = openSse({
      url: `${api.base()}/api/v1/sessions/${this.data.sessionId}/messages`,
      token: api.getAccessToken(),
      data: { content, stream: true },
      onEvent: (event, payload) => {
        if (event === 'meta') {
          this._patchAi({ userMessageId: payload.user_message_id })
        } else if (event === 'delta') {
          if (this.data.typing) this.setData({ typing: false })
          this._streamText += payload.content || ''
          this._patchAi({ content: this._streamText })
          this.scrollToBottom()
        } else if (event === 'crisis') {
          this.applyCrisis(payload)
        } else if (event === 'emotion') {
          // P3：本轮情绪识别角标（type / intensity / evidence）
          this._patchAi({ emotion: decorateEmotion(payload) })
        } else if (event === 'done') {
          this.finishTurn(payload.degraded)
        } else if (event === 'error') {
          this.handleStreamBreak()
        }
      },
      onError: (err) => {
        if (err && err.code === -2) {
          // 不支持分块：该请求未走对话，直接非流式
          this.sendNonStream(content)
        } else {
          this.handleStreamBreak()
        }
      },
      onComplete: () => {
        // done 事件已收尾；兜底
        if (this.data.sending) this.finishTurn(false)
      },
    })
  },

  // 非流式（弱网/旧基础库降级）
  sendNonStream(content) {
    api
      .post(`/api/v1/sessions/${this.data.sessionId}/messages`, { content, stream: false })
      .then((d) => {
        if (d.crisis) this.applyCrisis(d.crisis)
        this._streamText = d.assistant_reply || ''
        this._patchAi({
          content: d.assistant_reply || '',
          degraded: !!d.degraded,
          emotion: decorateEmotion(d.emotion),
        })
        this.finishTurn(!!d.degraded)
      })
      .catch((err) => {
        this._patchAi({ content: '刚刚网络开了个小差，等一下再发给我好吗？', degraded: true })
        this.setData({ sending: false, typing: false })
        wx.showToast({ title: (err && err.message) || '发送失败', icon: 'none' })
      })
  },

  // 流式中断：已收到内容则保留；无内容则本地提示（不自动重发，避免重复落库）
  handleStreamBreak() {
    if (!this._streamText) {
      this._patchAi({ content: '刚刚网络开了个小差，等一下再发给我好吗？', degraded: true })
    }
    this.setData({ sending: false, typing: false })
    wx.showToast({ title: '连接中断，已保留已回复内容', icon: 'none' })
  },

  applyCrisis(payload) {
    if (!payload || !payload.show_card) return
    if (payload.level === 'high') {
      this.setData({ highCard: { level: 'high', resources: payload.resources || [] } })
    } else if (payload.level === 'mid') {
      const cardKey = `m${this.data.seq++}`
      // mid 卡片插到 AI 回复之后
      const idx = this._aiIndex()
      const messages = this.data.messages.slice()
      messages.splice(idx + 1, 0, { key: cardKey, card: 'mid', resources: payload.resources || [] })
      this.setData({ messages })
      this.scrollToBottom()
    }
  },

  onDismissMid(e) {
    // 关闭对应的 mid 卡片（e.target 标记 key 由 dataset 提供）
    const key = e.currentTarget.dataset.key
    this.setData({ messages: this.data.messages.filter((m) => m.key !== key) })
  },

  finishTurn(degraded) {
    if (this._sseTask) this._sseTask = null
    this._patchAi({ degraded: !!degraded, content: this._streamText || '我在听。' })
    this.setData({ sending: false, typing: false })
    this.scrollToBottom()
  },

  scrollToBottom() {
    const last = this.data.messages[this.data.messages.length - 1]
    if (last) {
      wx.nextTick(() => this.setData({ scrollTo: last.key }))
    }
  },
})
