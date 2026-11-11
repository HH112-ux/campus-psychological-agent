// config.js —— 小程序环境配置（发布地址的唯一入口，按微信 envVersion 自动选择）
// apiBase 必须与微信公众平台「开发管理 → 服务器域名 → request 合法域名」完全一致；
// 体验版 / 正式版必须为已备案的 HTTPS 域名，留空时请求会立即失败并在控制台报错（快速暴露漏配）。
const API_BASE = {
  // 本地开发者工具 / 真机调试（真机需改成电脑局域网 IP，见 README）
  develop: 'http://127.0.0.1:8000',
  // 体验版：填入已备案的 HTTPS 域名，如 https://your-domain.example
  trial: '',
  // 正式版：填入已备案的 HTTPS 域名（与后台「服务器域名」一致）
  release: '',
}

function currentEnvVersion() {
  try {
    return (wx.getAccountInfoSync().miniProgram.envVersion || '').trim() || 'develop'
  } catch (e) {
    // 低版本基础库 / 非小程序环境（如语法检查）下退化为 develop
    return 'develop'
  }
}

const envVersion = currentEnvVersion()
const apiBase = API_BASE[envVersion] || ''

if (!apiBase) {
  console.error(
    `[config] ${envVersion} 环境的 apiBase 未配置：请在 miniprogram/config.js 的 API_BASE.${envVersion} 填写已备案的 HTTPS 域名`
  )
}

module.exports = { envVersion, apiBase }
