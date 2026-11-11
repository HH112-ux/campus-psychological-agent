// tests/sse-status.test.js —— B-10：流式响应必须校验状态码与 content-type
// 修前：非 2xx 的 JSON 错误体被当成 SSE 静默丢弃，页面回落成伪造的「我在听。」
// 修后：非 2xx / 非 text/event-stream 一律走 onError，不触发 onEvent/onComplete
const test = require('node:test')
const assert = require('node:assert/strict')

const { openSse } = require('../utils/sse')

function harness(chunks = []) {
  const state = { requests: [], events: [], errors: [], completes: 0, aborted: false }
  const queue = chunks.slice()
  global.wx = {
    request(opts) {
      state.requests.push(opts)
      return {
        abort() {
          state.aborted = true
        },
        onChunkReceived(cb) {
          queue.forEach((chunk) => cb({ data: chunk }))
        },
      }
    },
  }
  const start = () =>
    openSse({
      url: 'https://example.test/api/v1/sessions/s1/messages',
      data: { content: '你好', stream: true },
      token: 't',
      onEvent: (event, payload) => state.events.push({ event, payload }),
      onError: (err) => state.errors.push(err),
      onComplete: () => {
        state.completes += 1
      },
    })
  const finish = (res) => state.requests[state.requests.length - 1].success(res)
  return { state, start, finish }
}

const bytes = (text) => new TextEncoder().encode(text)

test('401 JSON：走错误分支，不产生事件、不触发完成回调', () => {
  const h = harness()
  h.start()
  h.finish({
    statusCode: 401,
    header: { 'Content-Type': 'application/json' },
    data: '{"code":1002,"message":"请重新登录"}',
  })

  assert.equal(h.state.errors.length, 1, '必须进入 onError')
  assert.equal(h.state.errors[0].statusCode, 401)
  assert.match(h.state.errors[0].body, /请重新登录/)
  assert.equal(h.state.events.length, 0, '错误体不得被当作 SSE 事件')
  assert.equal(h.state.completes, 0, '错误响应不得触发 onComplete')
})

test('500 非事件流：同样进入错误分支', () => {
  const h = harness([bytes('<html>Internal Server Error</html>')])
  h.start()
  h.finish({
    statusCode: 500,
    header: { 'Content-Type': 'text/html' },
    data: '',
  })

  assert.equal(h.state.errors.length, 1)
  assert.equal(h.state.errors[0].statusCode, 500)
  assert.equal(h.state.completes, 0)
})

test('200 但 content-type 为 application/json（stream_enabled=false）：错误分支并保留正文', () => {
  const body = JSON.stringify({
    code: 0,
    message: 'ok',
    data: { assistant_reply: '我在。', degraded: false },
  })
  const h = harness([bytes(body)])
  h.start()
  h.finish({
    statusCode: 200,
    header: { 'Content-Type': 'application/json; charset=utf-8' },
    data: '',
  })

  assert.equal(h.state.errors.length, 1)
  assert.equal(h.state.errors[0].code, -3)
  assert.equal(h.state.errors[0].body, body, '正文需交给上层按普通响应渲染')
  assert.equal(h.state.events.length, 0)
  assert.equal(h.state.completes, 0)
})

test('200 + text/event-stream：正常解析并完成', () => {
  const h = harness([bytes('event: delta\ndata: {"content":"你好"}\n\n')])
  h.start()
  h.finish({
    statusCode: 200,
    header: { 'Content-Type': 'text/event-stream; charset=utf-8' },
    data: '',
  })

  assert.equal(h.state.errors.length, 0)
  assert.deepEqual(h.state.events, [{ event: 'delta', payload: { content: '你好' } }])
  assert.equal(h.state.completes, 1)
})
