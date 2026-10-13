// components/crisis-card/crisis-card.js
Component({
  properties: {
    level: { type: String, value: 'high' }, // high | mid
    resources: { type: Array, value: [] },
    closable: { type: Boolean, value: false }, // high 常驻不可关；mid 可关
  },
  data: {
    title: '',
    subtitle: '',
  },
  observers: {
    level(v) {
      if (v === 'high') {
        this.setData({
          title: '你此刻的安全最重要',
          subtitle: '如果你有伤害自己的念头或计划，请立刻联系下面的人，你不是一个人在扛。',
        })
      } else {
        this.setData({
          title: '最近好像有点难',
          subtitle: '如果情绪一直很重，这些渠道可以免费、匿名地陪你聊聊。',
        })
      }
    },
    resources(list) {
      const decorated = (list || []).map((r) => ({
        ...r,
        _callable: !!r.phone && r.phone.indexOf('X') === -1 && r.phone.indexOf('x') === -1,
      }))
      this.setData({ _items: decorated })
    },
  },
  data: {
    title: '',
    subtitle: '',
    _items: [],
  },
  methods: {
    onCall(e) {
      const phone = e.currentTarget.dataset.phone
      const callable = e.currentTarget.dataset.callable
      if (!callable) {
        wx.showToast({ title: '该电话待补充', icon: 'none' })
        return
      }
      wx.makePhoneCall({
        phoneNumber: phone,
        fail: () => {},
      })
    },
    onDismiss() {
      this.triggerEvent('dismiss')
    },
  },
})
