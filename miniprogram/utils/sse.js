// utils/sse.js —— 小程序 SSE 客户端：enableChunked 接收、跨 chunk 安全 UTF-8 解码、按帧解析
/**
 * 用法：
 *   const task = openSse({ url, data, token, onEvent, onError, onComplete, idleMs })
 *   task.abort()
 */

// 跨 chunk 的增量 UTF-8 解码器：末尾多字节字符被截断时，留到下一块补全
function createUtf8Decoder() {
  let pending = []
  return function decode(arrayBuffer) {
    let bytes = new Uint8Array(arrayBuffer)
    if (pending.length) {
      const merged = new Uint8Array(pending.length + bytes.length)
      merged.set(new Uint8Array(pending), 0)
      merged.set(bytes, pending.length)
      bytes = merged
    }
    let out = ''
    let i = 0
    while (i < bytes.length) {
      const b = bytes[i]
      if (b < 0x80) {
        out += String.fromCharCode(b)
        i += 1
        continue
      }
      const n = b >= 0xf0 ? 4 : b >= 0xe0 ? 3 : 2
      if (i + n > bytes.length) break // 不完整，留待下一块
      let cp
      if (n === 2) cp = ((b & 0x1f) << 6) | (bytes[i + 1] & 0x3f)
      else if (n === 3) cp = ((b & 0x0f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f)
      else
        cp =
          ((b & 0x07) << 18) |
          ((bytes[i + 1] & 0x3f) << 12) |
          ((bytes[i + 2] & 0x3f) << 6) |
          (bytes[i + 3] & 0x3f)
      if (cp > 0xffff) {
        cp -= 0x10000
        out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 0x3ff))
      } else {
        out += String.fromCharCode(cp)
      }
      i += n
    }
    pending = Array.from(bytes.slice(i))
    return out
  }
}

function parseFrame(raw, onEvent) {
  let event = 'message'
  const dataLines = []
  raw.split('\n').forEach((line) => {
    if (line.indexOf('event:') === 0) event = line.slice(6).trim()
    else if (line.indexOf('data:') === 0) dataLines.push(line.slice(5).trim())
  })
  if (!dataLines.length) return
  const rawData = dataLines.join('')
  let payload
  try {
    payload = JSON.parse(rawData)
  } catch (e) {
    payload = rawData
  }
  onEvent(event, payload)
}

function openSse({ url, data, token, onEvent, onError, onComplete, idleMs = 10000 }) {
  const decoder = createUtf8Decoder()
  let buffer = ''
  let timer = null
  let finished = false

  const clearIdle = () => {
    if (timer) clearTimeout(timer)
    timer = null
  }
  const armIdle = () => {
    clearIdle()
    timer = setTimeout(() => {
      // 超时未收到任何增量，主动中断交由上层降级/重试
      if (!finished) {
        finished = true
        try {
          task.abort()
        } catch (e) {}
        onError && onError({ code: -1, message: '接收超时' })
      }
    }, idleMs)
  }

  const task = wx.request({
    url,
    method: 'POST',
    data,
    enableChunked: true,
    responseType: 'text',
    header: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    success() {
      if (finished) return
      finished = true
      clearIdle()
      // 处理可能残留的最后一帧
      if (buffer.trim()) parseFrame(buffer, onEvent)
      onComplete && onComplete()
    },
    fail(err) {
      if (finished) return
      finished = true
      clearIdle()
      onError && onError({ code: -1, message: '网络中断', raw: err })
    },
  })

  if (task && typeof task.onChunkReceived === 'function') {
    task.onChunkReceived(({ data: chunk }) => {
      armIdle()
      buffer += decoder(chunk)
      let idx
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        parseFrame(raw, onEvent)
      }
    })
  } else {
    // 基础库不支持分块接收，直接判定不支持，交给上层走非流式降级
    finished = true
    clearIdle()
    onError && onError({ code: -2, message: 'unsupported_chunk' })
  }

  armIdle()
  return task
}

module.exports = { openSse }
