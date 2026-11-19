<script setup>
import { computed, ref } from 'vue'
import { applyFix, FIXER_MESSAGES, previewFix, rollbackFix } from '@api/fixer.js'

const props = defineProps({
  issue: { type: Object, required: true },
  repoId: { type: String, default: '' },
})

const emit = defineEmits(['applied'])

const open = ref(false)
const loading = ref(false)
const error = ref(null)
const preview = ref(null)
const selectedIds = ref([])
const backupDir = ref('')
const applyResult = ref(null)
const rollbackResult = ref(null)
const fixerAvailable = ref(typeof window !== 'undefined' && Boolean(window.repoguard?.pickDirectory))

const FIXABLE_RULES = ['link-005', 'code-012', 'code-010']
const ruleFixable = computed(() => FIXABLE_RULES.includes(props.issue?.rule_id))
const canShow = computed(() => ruleFixable.value && fixerAvailable.value)
const showHint = computed(() => ruleFixable.value && !fixerAvailable.value)
const patches = computed(() => (Array.isArray(preview.value?.patches) ? preview.value.patches : []))
const fixablePatches = computed(() => patches.value.filter((patch) => patch.fixable))

function fail(err) {
  error.value = {
    code: err?.code || 'NETWORK_ERROR',
    message: FIXER_MESSAGES[err?.code] || err?.message || '请求失败',
    detail: err?.detail || '',
    requestId: err?.requestId || '',
  }
}

async function openDialog() {
  if (!canShow.value || !props.repoId) return
  open.value = true
  loading.value = true
  error.value = null
  preview.value = null
  applyResult.value = null
  rollbackResult.value = null
  selectedIds.value = []
  try {
    preview.value = await previewFix({
      repo: props.repoId,
      issues: [
        {
          file_path: props.issue.file_path,
          line_no: props.issue.line_no,
          rule_id: props.issue.rule_id,
          excerpt: props.issue.excerpt || '',
        },
      ],
      strict: false,
    })
    selectedIds.value = fixablePatches.value.map((patch) => patch.patch_id)
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

async function pickBackup() {
  if (!fixerAvailable.value) return
  error.value = null
  try {
    const picked = await window.repoguard.pickDirectory()
    if (picked) backupDir.value = String(picked)
  } catch (err) {
    fail(err)
  }
}

async function confirmApply() {
  if (!selectedIds.value.length || !backupDir.value) return
  const selections = fixablePatches.value
    .filter((patch) => selectedIds.value.includes(patch.patch_id))
    .map((patch) => ({
      file_path: patch.file_path,
      line_no: patch.line_no,
      rule_id: patch.rule_id,
      old_line: patch.old_line,
    }))
  loading.value = true
  error.value = null
  try {
    applyResult.value = await applyFix({
      repo: props.repoId,
      backupDir: backupDir.value,
      selections,
      onStale: 'skip',
      strict: false,
    })
    emit('applied')
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

async function rollbackApplied() {
  if (!applyResult.value?.backup_id || !applyResult.value?.backups?.length) return
  loading.value = true
  error.value = null
  try {
    rollbackResult.value = await rollbackFix({
      repo: props.repoId,
      backupDir: backupDir.value,
      backupId: applyResult.value.backup_id,
      backups: applyResult.value.backups.map((item) => ({
        file_path: item.file_path,
        backup_path: item.backup_path,
        after_sha256: item.after_sha256,
      })),
      force: false,
      strict: false,
    })
    emit('applied')
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

function diffLines(patch) {
  return String(patch.diff || '').split('\n')
}

function diffClass(line) {
  if (line.startsWith('@@')) return 'is-hunk'
  if (line.startsWith('+++') || line.startsWith('---')) return 'is-meta'
  if (line.startsWith('+')) return 'is-add'
  if (line.startsWith('-')) return 'is-del'
  return ''
}

function diffLabel(line) {
  if (line.startsWith('@@')) return '位置 '
  if (line.startsWith('+++') || line.startsWith('---')) return ''
  if (line.startsWith('+')) return '新增 '
  if (line.startsWith('-')) return '删除 '
  return ''
}
</script>

<template>
  <span class="fixer-entry">
    <button v-if="canShow" type="button" class="btn" @click="openDialog">查看修复</button>
    <span v-else-if="showHint" class="fixer-hint">修复功能仅在桌面版可用</span>
  </span>

  <div v-if="open" class="fixer-backdrop" @click.self="open = false">
    <section class="fixer-dialog" role="dialog" aria-modal="true" aria-labelledby="fixer-title">
      <header class="fixer-head">
        <h2 id="fixer-title">{{ issue.rule_id }} 修复预览</h2>
        <button type="button" class="btn" @click="open = false">关闭</button>
      </header>

      <p v-if="loading" class="fixer-muted">处理中…</p>

      <div v-if="error" class="fixer-error" role="alert">
        <strong>{{ error.message }}</strong>
        <span v-if="error.code">（{{ error.code }}）</span>
        <p v-if="error.detail">{{ error.detail }}</p>
        <p v-if="error.requestId">request_id：{{ error.requestId }}</p>
      </div>

      <template v-if="preview">
        <p class="fixer-muted">仓库：{{ preview.repo }}</p>
        <ul class="fixer-patches">
          <li v-for="patch in patches" :key="patch.patch_id || `${patch.file_path}:${patch.line_no}`">
            <label v-if="patch.fixable" class="fixer-check">
              <input v-model="selectedIds" type="checkbox" :value="patch.patch_id" />
              {{ patch.file_path }}:{{ patch.line_no }}
            </label>
            <p v-else class="fixer-unfixable">{{ patch.file_path }}:{{ patch.line_no }} — {{ patch.reason }}</p>
            <template v-if="patch.fixable">
              <p class="fixer-lines">
                <span class="fixer-old">旧：{{ patch.old_line }}</span>
                <span class="fixer-new">新：{{ patch.new_line }}</span>
              </p>
              <pre class="fixer-diff"><span v-for="(line, index) in diffLines(patch)" :key="index" class="fixer-diff-line" :class="diffClass(line)">{{ diffLabel(line) }}{{ line }}</span></pre>
            </template>
          </li>
        </ul>
        <div class="fixer-actions">
          <button type="button" class="btn" :disabled="loading" @click="pickBackup">选择备份目录</button>
          <button type="button" class="btn btn--primary" :disabled="loading || !selectedIds.length || !backupDir" @click="confirmApply">
            确认写入
          </button>
        </div>
        <p v-if="backupDir" class="fixer-muted">备份目录已选择（仓库外）</p>
      </template>

      <div v-if="applyResult" class="fixer-result">
        <p>已写入 {{ applyResult.applied.length }} 条，跳过 {{ applyResult.skipped.length }} 条，备份 {{ applyResult.backups.length }} 个文件。</p>
        <button v-if="applyResult.backup_id && applyResult.backups.length" type="button" class="btn" :disabled="loading" @click="rollbackApplied">
          回滚本次写入
        </button>
      </div>

      <div v-if="rollbackResult" class="fixer-result">
        <p>已还原 {{ rollbackResult.restored.length }} 个文件，失败 {{ rollbackResult.failed.length }} 个。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fixer-entry { display: inline-block; margin-top: 8px; }
.fixer-hint, .fixer-muted { color: var(--color-muted); font-size: 12px; }
.fixer-backdrop { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(8, 16, 28, 0.55); }
.fixer-dialog { width: min(880px, 100%); max-height: 85vh; overflow: auto; padding: 16px 18px; border: 1px solid var(--color-border); border-radius: var(--radius); background: var(--color-surface); color: var(--color-text); box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28); }
.fixer-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.fixer-head h2 { margin: 0; font-size: 16px; }
.fixer-patches { list-style: none; padding: 0; margin: 8px 0; display: grid; gap: 10px; }
.fixer-patches li { border: 1px solid var(--color-border); border-radius: 8px; padding: 8px 10px; }
.fixer-check { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.fixer-unfixable { margin: 0; color: var(--color-muted); font-size: 12px; }
.fixer-lines { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 6px 0; font-size: 12px; }
.fixer-old { color: var(--color-high); }
.fixer-new { color: var(--color-accent-2); }
.fixer-diff { margin: 6px 0 0; padding: 8px; max-height: 180px; overflow: auto; border-radius: 6px; background: var(--color-code-bg); font-size: 12px; white-space: pre-wrap; word-break: break-word; }
.fixer-diff-line { display: block; }
.fixer-diff-line.is-add { color: var(--color-accent-2); }
.fixer-diff-line.is-del { color: var(--color-high); }
.fixer-diff-line.is-hunk, .fixer-diff-line.is-meta { color: var(--color-muted); }
.fixer-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
.fixer-error { border: 1px solid var(--color-high); border-radius: 8px; padding: 8px 10px; background: var(--color-error-bg); color: var(--color-error-text); font-size: 12px; }
.fixer-error p { margin: 4px 0 0; }
.fixer-result { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--color-border); font-size: 13px; }
</style>