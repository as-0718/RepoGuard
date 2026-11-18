<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { checkRepo } from '@api/dashboard.js'
import { getStoredRepo, setStoredRepo } from '@api/repoStore.js'
import ThemeToggle from '../components/ThemeToggle.vue'

const route = useRoute()
const router = useRouter()

const path = ref(getStoredRepo())
const checking = ref(false)
const checked = ref(null)
const error = ref(null)

// Electron preload 暴露了目录选择接口时才显示「浏览」按钮；浏览器开发态仅支持粘贴路径。
const canPick = typeof window !== 'undefined' && Boolean(window.repoguard?.pickDirectory)

const inputHint = computed(() =>
  canPick ? '粘贴项目文件夹的绝对路径，或点击「浏览」选择目录' : '请粘贴项目文件夹的绝对路径（当前环境不支持目录浏览）',
)

async function browse() {
  if (!canPick) return
  error.value = null
  try {
    const picked = await window.repoguard.pickDirectory()
    if (picked) {
      path.value = picked
      checked.value = null
      error.value = null
    }
  } catch (err) {
    error.value = { message: err?.message || '选择目录失败', detail: '' }
  }
}

async function submit() {
  const target = path.value.trim()
  if (!target) {
    error.value = { message: '请填写仓库路径', detail: '' }
    return
  }
  checking.value = true
  error.value = null
  checked.value = null
  try {
    const res = await checkRepo({ path: target })
    checked.value = res
    setStoredRepo(res.path)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect ? route.query.redirect : '/overview'
    router.push({ path: redirect, query: { repo: res.path } })
  } catch (err) {
    error.value = {
      code: err?.code || '',
      message: err?.message || '校验失败',
      detail: err?.detail || '',
    }
  } finally {
    checking.value = false
  }
}

function backWelcome() {
  router.push('/welcome')
}
</script>

<template>
  <div class="select-page">
    <ThemeToggle class="theme-toggle--float" />
    <section class="select-card card">
      <h1 class="page-title">选择要巡检的仓库</h1>
      <p class="page-subtitle">{{ inputHint }}</p>

      <div class="field-row">
        <input
          v-model="path"
          class="path-input"
          type="text"
          placeholder="例如 C:\Users\你\Desktop\my-project"
          spellcheck="false"
          @keyup.enter="submit"
        />
        <button v-if="canPick" type="button" class="btn" :disabled="checking" @click="browse">浏览…</button>
      </div>

      <div v-if="error" class="error-banner" role="alert">
        <strong>{{ error.message }}</strong>
        <span v-if="error.detail">：{{ error.detail }}</span>
      </div>

      <div v-if="checked" class="notice" role="status">
        已识别仓库 <strong>{{ checked.name }}</strong>，共 {{ checked.file_count }} 个文件，正在生成报告…
      </div>

      <div class="select-actions">
        <button type="button" class="btn btn--primary" :disabled="checking" @click="submit">
          {{ checking ? '校验中…' : '校验并生成报告' }}
        </button>
        <button type="button" class="btn" :disabled="checking" @click="backWelcome">返回须知</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.select-page {
  min-height: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
}

.select-card {
  width: 100%;
  max-width: 720px;
}

.field-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.path-input {
  flex: 1;
  font: inherit;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  color: var(--color-text);
}

.select-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.select-actions .btn {
  padding: 8px 18px;
}
</style>
