// pages/practice/practice.js —— 练习卡片（V4）：呼吸引导 / 正念呼吸空间 / 行为激活
// 内容仅供放松与觉察，不替代专业帮助；完成记录回传后端落库（practice_logs）。
const api = require('../../utils/api')

const CATEGORY_LABEL = {
  breathing: '呼吸练习',
  mindfulness: '正念练习',
  activation: '行动激活',
}

const PHASE_TEXT = { inhale: '吸气', hold: '屏息', exhale: '呼气', rest: '停留' }
const PHASE_SCALE = { inhale: 1.6, hold: 1.6, exhale: 1.0, rest: 1.0 }

function fmt(sec) {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m + ':' + (s < 10 ? '0' : '') + s
}

Page({
  data: {
    practices: [],
    active: null, // 当前打开的卡片
    running: false,
    remainText: '0:00',
    breathText: '',
    breathScale: 1,
    phaseSeconds: 1,
    stepIndex: -1,
    checked: {},
  },

  onShow() {
    this.load()
  },

  onUnload() {
    this.stopTimer()
  },

  load() {
    api
      .ensureLogin()
      .then(() => api.get('/api/v1/practices'))
      .then((d) => {
        const practices = d.practices.map((p) => ({
          ...p,
          categoryLabel: CATEGORY_LABEL[p.category] || '练习',
          durationText: fmt(p.duration_seconds),
        }))
        this.setData({ practices })
      })
      .catch(() => wx.showToast({ title: '加载失败，请稍后重试', icon: 'none' }))
  },

  openCard(e) {
    const id = e.currentTarget.dataset.id
    const card = this.data.practices.find((p) => p.id === id)
    if (!card) return
    this.stopTimer()
    this.remainSeconds = card.duration_seconds
    this.setData({
      active: card,
      running: false,
      remainText: fmt(card.duration_seconds),
      breathText: '',
      breathScale: 1,
      phaseSeconds: 1,
      stepIndex: -1,
      checked: {},
    })
  },

  closeCard() {
    this.stopTimer()
    this.setData({ active: null, running: false, breathText: '', breathScale: 1 })
  },

  // 阻止遮罩点击穿透（点击卡片面板本身不关闭）
  noop() {},

  toggleTask(e) {
    const i = e.currentTarget.dataset.index
    const checked = { ...this.data.checked, [i]: !this.data.checked[i] }
    this.setData({ checked })
  },

  toggleRun() {
    if (this.data.running) {
      this.stopTimer()
      this.setData({ running: false })
      return
    }
    const card = this.data.active
    if (!card) return
    if (this.remainSeconds == null || this.remainSeconds <= 0) {
      this.remainSeconds = card.duration_seconds
    }
    if (card.category === 'breathing') {
      this.phases = this.buildPhases(card.pattern)
      this.phaseIdx = 0
      this.phaseRemain = this.phases.length ? this.phases[0].seconds : 0
      if (this.phases.length) this.applyPhase()
    }
    this.setData({ running: true })
    this.startTimer()
  },

  buildPhases(pattern) {
    if (!pattern) return []
    const phases = []
    ;['inhale', 'hold', 'exhale', 'rest'].forEach((k) => {
      if (pattern[k]) phases.push({ name: k, seconds: pattern[k] })
    })
    return phases
  },

  applyPhase() {
    const phase = this.phases[this.phaseIdx]
    this.setData({
      breathText: PHASE_TEXT[phase.name],
      breathScale: PHASE_SCALE[phase.name],
      phaseSeconds: phase.seconds,
    })
  },

  startTimer() {
    this.stopTimer()
    this.timer = setInterval(() => this.tick(), 1000)
  },

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  },

  tick() {
    const card = this.data.active
    if (!card || this.remainSeconds == null || this.remainSeconds <= 0) return
    this.remainSeconds -= 1
    const patch = { remainText: fmt(this.remainSeconds) }

    if (card.category === 'breathing' && this.phases && this.phases.length) {
      this.phaseRemain -= 1
      if (this.phaseRemain <= 0) {
        this.phaseIdx = (this.phaseIdx + 1) % this.phases.length
        const phase = this.phases[this.phaseIdx]
        this.phaseRemain = phase.seconds
        patch.breathText = PHASE_TEXT[phase.name]
        patch.breathScale = PHASE_SCALE[phase.name]
        patch.phaseSeconds = phase.seconds
      }
    } else if (card.category === 'mindfulness' && card.steps.length) {
      const elapsed = card.duration_seconds - this.remainSeconds
      const step = Math.min(
        card.steps.length - 1,
        Math.floor((elapsed / card.duration_seconds) * card.steps.length)
      )
      if (step !== this.data.stepIndex) patch.stepIndex = step
    }

    this.setData(patch)
    if (this.remainSeconds <= 0) {
      this.stopTimer()
      this.setData({ running: false, breathText: '', breathScale: 1 })
      this.complete(true)
    }
  },

  // 手动完成
  finish() {
    this.stopTimer()
    this.remainSeconds = 0
    this.setData({ running: false, breathText: '', breathScale: 1 })
    this.complete(false)
  },

  complete(auto) {
    const card = this.data.active
    if (!card) return
    api
      .post('/api/v1/practices/' + card.id + '/complete', {
        duration_seconds: card.duration_seconds,
      })
      .then(() => {
        wx.showToast({ title: auto ? '完成一次练习，很棒' : '已记录完成', icon: 'success' })
        this.closeCard()
        this.load()
      })
      .catch(() => wx.showToast({ title: '记录失败，请稍后重试', icon: 'none' }))
  },
})
