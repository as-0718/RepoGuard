<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [Number, String, null], default: null },
  unit: { type: String, default: '' },
  tone: { type: String, default: 'neutral' },
  clickable: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  icon: { type: String, default: '' },
  iconTone: { type: String, default: 'blue' },
  // { dir: 'up' | 'down' | 'flat', pct: number | null, good: boolean }
  delta: { type: Object, default: null },
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

const ICON_PATHS = {
  file: 'M7 3h7l5 5v11a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1zm7 0v5h5M9 13h6M9 17h6',
  alert: 'M12 3.5l9 16H3l9-16zM12 10v4m0 3.2v.2',
  bulb: 'M12 3a6 6 0 00-3.6 10.8c.7.6 1.1 1.3 1.3 2.2h4.6c.2-.9.6-1.6 1.3-2.2A6 6 0 0012 3zM9.5 19h5M10 21.5h4',
  ghost: 'M12 3a7 7 0 017 7v9l-2.3-2-2.4 2-2.3-2-2.3 2-2.4-2L5 19v-9a7 7 0 017-7zM9 10.5h.01M15 10.5h.01',
  help: 'M12 3a9 9 0 100 18 9 9 0 000-18zm-1.2 5.6a1.7 1.7 0 013.3.5c0 1.1-1.5 1.4-1.8 2.4M12 16.2v.2',
  degraded: 'M12 3l7.5 4v5.5c0 4.4-3.1 7.1-7.5 8.5-4.4-1.4-7.5-4.1-7.5-8.5V7L12 3zM12 10v3.5m0 2.8v.2',
  skip: 'M7 3h7l5 5v11a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1zm7 0v5h5M9 13l6 6m0-6l-6 6',
  clock: 'M12 3a9 9 0 100 18 9 9 0 000-18zm0 5v4l3 2',
  shield: 'M12 3l7.5 4v5.5c0 4.4-3.1 7.1-7.5 8.5-4.4-1.4-7.5-4.1-7.5-8.5V7L12 3zm-3 9l2 2 4-4',
  box: 'M3.5 8.5L12 4l8.5 4.5v7L12 20l-8.5-4.5v-7zM3.5 8.5L12 13l8.5-4.5M12 13v7',
  calendar: 'M5 6h14a1 1 0 011 1v11a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1zm3-3v4m8-4v4M4 10h16',
}

const iconPath = computed(() => ICON_PATHS[props.icon] || ICON_PATHS.file)

const deltaView = computed(() => {
  const d = props.delta
  if (!d || d.pct === null || d.pct === undefined || d.dir === 'flat') return null
  const arrow = d.dir === 'up' ? '↑' : '↓'
  const pct = `${Math.abs(d.pct).toFixed(0)}%`
  return { arrow, pct, good: Boolean(d.good), dir: d.dir }
})
</script>

<template>
  <div class="card kpi-card" :class="`kpi-card--${iconTone}`">
    <span v-if="icon" class="kpi-icon" aria-hidden="true">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path :d="iconPath" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </span>
    <div class="kpi-body">
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
      <div v-if="deltaView" class="kpi-delta" :class="deltaView.good ? 'kpi-delta--good' : 'kpi-delta--bad'">
        <span class="kpi-delta__arrow">{{ deltaView.arrow }}</span>
        <span>{{ deltaView.pct }}</span>
        <span class="kpi-delta__label">较上次巡检</span>
      </div>
      <span v-if="hint" class="kpi-hint">{{ hint }}</span>
    </div>
  </div>
</template>
