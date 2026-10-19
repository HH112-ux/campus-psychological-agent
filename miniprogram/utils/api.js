// utils/api.js —— 统一请求封装：静默登录、JWT 自动携带、401 静默刷新并重放
const ACCESS_KEY = 'xinyu_access_token'
const REFRESH_KEY = 'xinyu_refresh_token'
const USER_KEY = 'xinyu_user'

function base() {
  return getApp().globalData.apiBase
}

// ---------- token 存取 ----------
function getAccessToken() {
  return wx.getStorageSync(ACCESS_KEY) || ''
}
function getRefreshToken() {
  return wx.getStorageSync(REFRESH_KEY) || ''
}
function setTokens(data) {
  wx.setStorageSync(ACCESS_KEY, data.access_token)
  wx.setStorageSync(REFRESH_KEY, data.refresh_token)
  if (data.consented !== undefined) {
    const u = wx.getStorageSync(USER_KEY) || {}
    u.consented = data.consented
    wx.setStorageSync(USER_KEY, u)
  }
}
function clearTokens() {
  wx.removeStorageSync(ACCESS_KEY)
  wx.removeStorageSync(REFRESH_KEY)
}

// ---------- 原始请求（Promise，解包统一响应 {code,message,data}） ----------
function rawRequest({ url, method = 'GET', data = {}, header = {}, auth = true, timeout = 15000 }) {
  const h = { 'Content-Type': 'application/json', ...header }
  if (auth) {
    const t = getAccessToken()
    if (t) h.Authorization = `Bearer ${t}`
  }
  return new Promise((resolve, reject) => {
    wx.request({
      url: base() + url,
      method,
      data,
      header: h,
      timeout,
      success(res) {
        const body = res.data || {}
        if (res.statusCode >= 200 && res.statusCode < 300 && body.code === 0) {
          resolve(body.data)
        } else {
          // 业务/HTTP 错误，携带 code 与 httpStatus，便于上层判断 401
          reject({
            code: typeof body.code === 'number' ? body.code : -1,
            message: body.message || `请求失败（${res.statusCode}）`,
            httpStatus: res.statusCode,
            data: body.data,
          })
        }
      },
      fail(err) {
        reject({ code: -1, message: '网络异常，请稍后重试', raw: err })
      },
    })
  })
}

// ---------- 微信静默登录 ----------
let loginPromise = null
function wxLogin() {
  if (loginPromise) return loginPromise
  loginPromise = new Promise((resolve, reject) => {
    wx.login({
      success: ({ code }) => {
        rawRequest({
          url: '/api/v1/auth/wx-login',
          method: 'POST',
          data: { code: code || 'mock-code' },
          auth: false,
        })
          .then((data) => {
            setTokens(data)
            resolve(data)
          })
          .catch(reject)
      },
      fail: () => reject({ code: -1, message: '微信登录失败' }),
    })
  }).finally(() => {
    loginPromise = null
  })
  return loginPromise
}

function ensureLogin(force = false) {
  if (!force && getAccessToken()) return Promise.resolve()
  return wxLogin()
}

// ---------- 刷新 token（并发共享一次） ----------
let refreshPromise = null
function tryRefresh() {
  if (refreshPromise) return refreshPromise
  const rt = getRefreshToken()
  if (!rt) return Promise.reject(new Error('无 refresh_token'))
  refreshPromise = rawRequest({
    url: '/api/v1/auth/refresh',
    method: 'POST',
    data: { refresh_token: rt },
    auth: false,
  })
    .then((data) => {
      setTokens(data)
      return data
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

// ---------- 业务请求（自动登录 + 401 刷新/重登 + 重放一次） ----------
async function request(config, depth = 0) {
  await ensureLogin()
  try {
    return await rawRequest(config)
  } catch (err) {
    const unauthorized = err.httpStatus === 401 || err.code === 1002 || err.code === 1003
    if (!unauthorized) throw err
    if (depth === 0) {
      try {
        await tryRefresh()
        return await request(config, 1)
      } catch (e) {
        // 刷新失败，落到重新登录
      }
    }
    if (depth <= 1) {
      clearTokens()
      await ensureLogin(true)
      return await request(config, 2)
    }
    throw err
  }
}

// ---------- 文件上传（V5 语音转写等） ----------
// wx.uploadFile 不支持 rawRequest 的通用封装，单独实现：同样解包 {code,message,data}
async function uploadFile({ url, filePath, name = 'file', formData = {}, timeout = 30000 }) {
  await ensureLogin()
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: base() + url,
      filePath,
      name,
      formData,
      header: { Authorization: `Bearer ${getAccessToken()}` },
      timeout,
      success(res) {
        let body = {}
        try {
          body = JSON.parse(res.data || '{}')
        } catch (e) {}
        if (res.statusCode >= 200 && res.statusCode < 300 && body.code === 0) {
          resolve(body.data)
        } else {
          reject({
            code: typeof body.code === 'number' ? body.code : -1,
            message: body.message || `上传失败（${res.statusCode}）`,
            httpStatus: res.statusCode,
          })
        }
      },
      fail() {
        reject({ code: -1, message: '网络异常，请稍后重试' })
      },
    })
  })
}

// ---------- 对外 ----------
module.exports = {
  base,
  getAccessToken,
  getRefreshToken,
  clearTokens,
  ensureLogin,
  request,
  rawRequest,
  getLocalUser() {
    return wx.getStorageSync(USER_KEY) || {}
  },
  get(url, extra = {}) {
    return request({ url, method: 'GET', ...extra })
  },
  post(url, data, extra = {}) {
    return request({ url, method: 'POST', data, ...extra })
  },
  patch(url, data, extra = {}) {
    return request({ url, method: 'PATCH', data, ...extra })
  },
  put(url, data, extra = {}) {
    return request({ url, method: 'PUT', data, ...extra })
  },
  del(url, extra = {}) {
    return request({ url, method: 'DELETE', ...extra })
  },
  uploadFile,
  // V5 语音转写：上传录音文件，返回 { text }（音频转写后即弃，后端不留存）
  transcribeAudio(filePath) {
    return uploadFile({ url: '/api/v1/speech/transcribe', filePath })
  },
}
