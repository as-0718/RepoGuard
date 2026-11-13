<script setup>
import { computed } from 'vue'
import { ERROR_CODE_MESSAGES } from '@api/client.js'

const props = defineProps({
  error: { type: Object, default: null },
  stale: { type: Boolean, default: false },
  retrying: { type: Boolean, default: false },
})

const emit = defineEmits(['retry'])

const visible = computed(() => Boolean(props.error))
const code = computed(() => props.error?.code || '')
const message = computed(
  () => ERROR_CODE_MESSAGES[code.value] || props.error?.message || '请求失败',
)
const detail = computed(() => props.error?.detail || '')
const requestId = computed(() => props.error?.requestId || '')
</script>

<template>
  <div v-if="visible" class="error-banner" role="alert" aria-live="assertive">
    <div class="error-banner__head">
      <strong>{{ message }}</strong>
      <span v-if="code" class="error-banner__code">{{ code }}</span>
      <button type="button" class="btn" :disabled="retrying" @click="emit('retry')">
        {{ retrying ? '重试中…' : '重试' }}
      </button>
    </div>
    <p v-if="detail" class="error-banner__detail">{{ detail }}</p>
    <p v-if="requestId" class="error-banner__meta">request_id：{{ requestId }}</p>
    <p v-if="stale" class="error-banner__meta">当前展示的是上一次成功数据，可能已过期。</p>
  </div>
</template>