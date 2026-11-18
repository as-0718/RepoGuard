import { ref } from 'vue'

const STORAGE_KEY = 'repoguard.theme'
const DEFAULT_THEME = 'dark'

function normalize(value) {
  return value === 'light' ? 'light' : 'dark'
}

export function getStoredTheme() {
  try {
    return normalize(localStorage.getItem(STORAGE_KEY))
  } catch {
    return DEFAULT_THEME
  }
}

// 全局响应式主题，供按钮图标与图表跟随更新
export const themeRef = ref(getStoredTheme())

export function applyTheme(theme) {
  const next = normalize(theme)
  themeRef.value = next
  document.documentElement.dataset.theme = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // 私密模式等场景下写入失败不影响本次使用
  }
}

export function initTheme() {
  applyTheme(getStoredTheme())
}

export function toggleTheme() {
  applyTheme(themeRef.value === 'dark' ? 'light' : 'dark')
  return themeRef.value
}
