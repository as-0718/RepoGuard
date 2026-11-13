<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [Number, String], default: null },
  unit: { type: String, default: '' },
  tone: { type: String, default: 'neutral' },
  clickable: { type: Boolean, default: false },
  hint: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const toneLabels = {
  neutral: '',
  high: '高风险',
  suggestion: '建议',
  muted: '未启用',
}

const displayValue = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') return '—'
  if (typeof props.value === 'number' && Number.isFinite(props.value)) {
    return props.value.toLocaleString('zh-CN')
  }
  return String(props.value)
})

const toneLabel = computed(() => toneLabels[props.tone] || '')
</script>

<template>
  <div class="card kpi-card">
    <dl>
      <dt>
        {{ label }}
        <span v-if="toneLabel" class="tone-tag" :class="`tone-tag--${tone}`">{{ toneLabel }}</span>
      </dt>
      <dd v-if="clickable">
        <button type="button" class="kpi-button" @click="emit('select')">
          <span>{{ displayValue }}</span>
          <span v-if="unit" class="kpi-unit">{{ unit }}</span>
        </button>
      </dd>
      <dd v-else>
        <span>{{ displayValue }}</span>
        <span v-if="unit" class="kpi-unit">{{ unit }}</span>
      </dd>
    </dl>
    <span v-if="hint" class="kpi-hint">{{ hint }}</span>
  </div>
</template>