// 本地记忆当前所选仓库（路径或示例仓库名），跨页面刷新后保留。
const KEY = 'repoguard.repo'

export function getStoredRepo() {
  try {
    return window.localStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

export function setStoredRepo(repo) {
  try {
    if (repo) window.localStorage.setItem(KEY, repo)
    else window.localStorage.removeItem(KEY)
  } catch {
    // localStorage 不可用时静默降级
  }
}

export function clearStoredRepo() {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // 忽略
  }
}
