<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getHistory, getOverview } from '@api/dashboard.js'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const ctx = inject('dashboardContext')
const route = useRoute()
const router = useRouter()

const data = ref(null)
const loading = ref(false)
const error = ref(null)
const truncatedHint = ref('')
const prevSnapshot = ref(null)

let controller = null
let requestSeq = 0
let lastTick = 0

const repoId = computed(() => ctx?.repoId?.value || '')
const snapshot = computed(() => data.value?.snapshot || null)
const summary = computed(() => data.value?.summary || {})
const charts = computed(() => data.value?.charts || {})

const riskValues = computed(() => {
  const risk = charts.value.risk_breakdown || {}
  return { high: Number(risk.high || 0), suggestion: Number(risk.suggestion || 0) }
})

const categoryRows = computed(() =>
  Array.isArray(charts.value.category_breakdown) ? charts.value.category_breakdown : [],
)
const topFileRows = computed(() => (Array.isArray(charts.value.top_files) ? charts.value.top_files : []))

const historyList = ref([])

const trendRows = computed(() => {
  const list = Array.isArray(historyList.value) ? historyList.value : []
  return [...list].reverse().slice(-7)
})

const hasDegraded = computed(() => {
  const meta = snapshot.value
  return Boolean(meta && (meta.status === '部分降级' || (meta.degraded || []).length > 0))
})

const riskEmpty = computed(() => riskValues.value.high + riskValues.value.suggestion === 0)
const categoryEmpty = computed(() => categoryRows.value.every((row) => Number(row.count || 0) === 0))
const trendEmpty = computed(() => trendRows.value.length === 0)
const topFilesEmpty = computed(() => topFileRows.value.length === 0)

function buildDelta(current, previous, lowerIsBetter) {
  const prev = Number(previous)
  const cur = Number(current)
  if (!Number.isFinite(prev) || prev === 0 || !Number.isFinite(cur)) return null
  const pct = ((cur - prev) / prev) * 100
  if (Math.abs(pct) < 0.5) return { dir: 'flat', pct: 0, good: true }
  return {
    dir: pct > 0 ? 'up' : 'down',
    pct,
    good: lowerIsBetter ? cur < prev : cur > prev,
  }
}

function formatDuration(ms) {
  const value = Number(ms)
  if (!Number.isFinite(value) || value < 0) return '—'
  if (value < 1000) return `${Math.round(value)} ms`
  const totalSec = value / 1000
  if (totalSec < 60) return `${totalSec.toFixed(1)} 秒`
  const min = Math.floor(totalSec / 60)
  const sec = Math.round(totalSec - min * 60)
  return `${min} 分 ${sec} 秒`
}

function shortTime(value) {
  if (!value) return '—'
  const text = String(value)
  return text.length >= 16 ? `${text.slice(0, 10)} ${text.slice(11, 16)}` : text
}

function shortDay(value) {
  if (!value) return '—'
  const text = String(value)
  return text.length >= 10 ? text.slice(5, 10) : text
}

const riskOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
  legend: { bottom: 0 },
  title: {
    text: String(summary.value.issue_count ?? 0),
    subtext: '总问题数',
    left: 'center',
    top: '32%',
    textStyle: { fontSize: 22, fontWeight: 700 },
    subtextStyle: { fontSize: 12 },
  },
  series: [
    {
      name: '风险构成',
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      data: [
        { name: '高风险', value: riskValues.value.high, itemStyle: { color: '#e56159' } },
        { name: '建议', value: riskValues.value.suggestion, itemStyle: { color: '#e3b045' } },
      ],
      label: { formatter: '{b}：{c}' },
    },
  ],
}))

const categoryOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 24, top: 12, bottom: 8, containLabel: true },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: { type: 'category', inverse: true, data: categoryRows.value.map((row) => row.category) },
  series: [
    {
      name: '问题数',
      type: 'bar',
      barWidth: 18,
      barMaxWidth: 24,
      data: categoryRows.value.map((row) => Number(row.count || 0)),
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: {
          type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#3b8bef' }, { offset: 1, color: '#1d70e3' }],
        },
      },
    },
  ],
}))

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
  xAxis: {
    type: 'category',
    data: trendRows.value.map((row) => shortDay(row.scanned_at)),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '问题数',
      type: 'bar',
      barWidth: 18,
      barMaxWidth: 28,
      data: trendRows.value.map((row) => Number(row.issue_count || 0)),
      itemStyle: {
        borderRadius: [4, 4, 0, 0],
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: '#34d399' }, { offset: 1, color: '#1fa878' }],
        },
      },
    },
  ],
}))

const topFilesOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 24, top: 12, bottom: 8, containLabel: true },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: {
    type: 'category',
    inverse: true,
    data: topFileRows.value.map((row) => row.file_path),
    axisLabel: { width: 180, overflow: 'truncate' },
  },
  series: [
    {
      name: '问题数',
      type: 'bar',
      barWidth: 18,
      barMaxWidth: 24,
      data: topFileRows.value.map((row) => Number(row.issue_count || 0)),
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: {
          type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#8b6ce0' }, { offset: 1, color: '#6d4ad3' }],
        },
      },
    },
  ],
}))

const topFilesTable = computed(() => ({
  columns: [
    { key: 'file_path', label: '文件路径' },
    { key: 'issue_count', label: '问题数' },
  ],
  rows: topFileRows.value,
}))

const mainKpis = computed(() => {
  const prev = prevSnapshot.value || {}
  return [
    {
      label: '文件数',
      value: data.value?.files_count,
      tone: 'neutral',
      icon: 'file',
      iconTone: 'blue',
      delta: buildDelta(data.value?.files_count, prev.files_count, false),
    },
    {
      label: '问题总数',
      value: summary.value.issue_count,
      tone: 'neutral',
      icon: 'alert',
      iconTone: 'blue',
      delta: buildDelta(summary.value.issue_count, prev.issue_count, true),
    },
    {
      label: '高风险',
      value: summary.value.must_fix_count,
      tone: 'high',
      clickable: true,
      icon: 'alert',
      iconTone: 'red',
      delta: buildDelta(summary.value.must_fix_count, prev.must_fix_count, true),
    },
    {
      label: '建议',
      value: summary.value.suggestion_count,
      tone: 'suggestion',
      clickable: true,
      icon: 'bulb',
      iconTone: 'gold',
      delta: buildDelta(summary.value.suggestion_count, prev.suggestion_count, true),
    },
  ]
})

const secondaryKpis = computed(() => [
  {
    label: '僵尸候选',
    value: summary.value.zombie_candidate_count,
    tone: 'neutral',
    icon: 'ghost',
    iconTone: 'muted',
    hint: '疑似不再被引用的遗留文件或代码，可结合实际确认是否删除。',
  },
  {
    label: '无法判定',
    value: summary.value.undetermined_count,
    tone: 'muted',
    icon: 'help',
    iconTone: 'muted',
    hint: '规则不足以确定结论，需要人工进一步核对。',
  },
  {
    label: '降级项',
    value: summary.value.degraded_count,
    tone: 'muted',
    icon: 'degraded',
    iconTone: 'muted',
    hint: '本次巡检中未能完整检查、被跳过或部分受限的部分。',
  },
  {
    label: '跳过文件',
    value: summary.value.skipped_file_count,
    tone: 'muted',
    icon: 'skip',
    iconTone: 'muted',
    hint: '因体积过大、二进制或编码等原因，未做内容扫描的文件。',
  },
  {
    label: '扫描耗时',
    value: snapshot.value?.duration_ms,
    unit: 'ms',
    tone: 'neutral',
    icon: 'clock',
    iconTone: 'muted',
    hint: '本次巡检从开始到结束的总耗时。',
  },
])

const statusBar = computed(() => {
  const meta = snapshot.value || {}
  const degraded = hasDegraded.value
  return [
    {
      icon: 'box',
      label: '仓库',
      value: repoId.value || '—',
      status: degraded ? '部分降级' : '已连接',
      tone: degraded ? 'gold' : 'green',
    },
    { icon: 'clock', label: '本次巡检耗时', value: formatDuration(meta.duration_ms) },
    { icon: 'calendar', label: '上次巡检', value: shortTime(meta.scanned_at) },
    {
      icon: 'shield',
      label: degraded ? '部分完成' : '巡检完成',
      value: `发现 ${summary.value.issue_count ?? 0} 个问题`,
      tone: degraded ? 'gold' : 'green',
    },
  ]
})

const STATUS_ICONS = {
  box: 'M3.5 8.5L12 4l8.5 4.5v7L12 20l-8.5-4.5v-7zM3.5 8.5L12 13l8.5-4.5M12 13v7',
  clock: 'M12 3a9 9 0 100 18 9 9 0 000-18zm0 5v4l3 2',
  calendar: 'M5 6h14a1 1 0 011 1v11a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1zm3-3v4m8-4v4M4 10h16',
  shield: 'M12 3l7.5 4v5.5c0 4.4-3.1 7.1-7.5 8.5-4.4-1.4-7.5-4.1-7.5-8.5V7L12 3zm-3 9l2 2 4-4',
}

async function load(forceRefresh) {
  const repo = repoId.value
  if (!repo) return
  controller?.abort()
  controller = new AbortController()
  const seq = ++requestSeq
  loading.value = true
  ctx?.setRequesting?.(true)
  error.value = null
  try {
    const [payload, historyPayload] = await Promise.all([
      getOverview({ repo, refresh: forceRefresh, signal: controller.signal }),
      getHistory({ repo, limit: 7, signal: controller.signal }).catch(() => null),
    ])
    if (seq !== requestSeq) return
    data.value = payload
    const historyRows = Array.isArray(historyPayload?.history) ? historyPayload.history : []
    historyList.value = historyRows
    // 仅非缓存命中才会把本次快照写库：本次已入库时上一次取第二条，否则取第一条。
    const cached = Boolean(payload?.snapshot?.cached)
    prevSnapshot.value = (cached ? historyRows[0] : historyRows[1]) || historyRows[0] || null
    ctx?.setSnapshotMeta?.(payload?.snapshot || null)
    clearRefreshParam()
  } catch (err) {
    if (err?.name === 'AbortError' || seq !== requestSeq) return
    error.value = {
      code: err?.code || 'NETWORK_ERROR',
      message: err?.message || '请求失败',
      detail: err?.detail || '',
      requestId: err?.requestId || '',
    }
  } finally {
    if (seq === requestSeq) {
      loading.value = false
      ctx?.setRequesting?.(false)
    }
  }
}

function clearRefreshParam() {
  if (!('refresh' in route.query) && !('_r' in route.query)) return
  const query = { ...route.query }
  delete query.refresh
  delete query._r
  router.replace({ query })
}

function goIssues(extra) {
  router.push({ path: '/issues', query: { repo: repoId.value, ...extra } })
}

function onRiskClick({ name }) {
  goIssues({ risk_level: name === '高风险' ? 'high' : 'suggestion' })
}

function onKpiSelect(item) {
  if (item.label === '高风险') goIssues({ risk_level: 'high' })
  else if (item.label === '建议') goIssues({ risk_level: 'suggestion' })
}

function onFileClick({ dataIndex }) {
  const row = topFileRows.value[dataIndex]
  if (!row?.file_path) return
  const keyword = String(row.file_path).slice(0, 64)
  truncatedHint.value =
    String(row.file_path).length > 64 ? `路径超过 64 字符，已截断为：${keyword}` : ''
  goIssues({ keyword })
}

watch(
  repoId,
  (repo) => {
    if (repo) load(false)
  },
  { immediate: true },
)

watch(
  () => ctx?.refreshTick?.value ?? 0,
  (tick) => {
    if (tick === lastTick) return
    lastTick = tick
    if (repoId.value) load(true)
  },
)

onBeforeUnmount(() => {
  requestSeq += 1
  controller?.abort()
  ctx?.setRequesting?.(false)
})
</script>

<template>
  <section>
    <h1 class="page-title">总览</h1>
    <p class="page-subtitle">当前仓库的只读巡检快照，数据来源为本地巡检引擎。</p>

    <LoadingSkeleton v-if="loading && !data" variant="kpi" :count="4" />

    <template v-else-if="error && !data">
      <ErrorBanner :error="error" @retry="load(false)" />
      <EmptyState
        title="暂无可用数据"
        description="请确认后端服务已启动，并在上方选择可用仓库。"
        icon="no-data"
      />
    </template>

    <template v-else-if="data">
      <div v-if="loading" class="progress-line" aria-hidden="true"></div>
      <ErrorBanner :error="error" :stale="true" @retry="load(false)" />

      <div v-if="hasDegraded" class="notice notice--degraded" role="status">
        本次巡检部分降级，数据可能不完整。
      </div>
      <div v-if="snapshot?.refresh_throttled" class="notice" role="status">
        刷新过于频繁，已展示最近一次快照。
      </div>
      <div v-if="truncatedHint" class="notice" role="status">{{ truncatedHint }}</div>

      <div class="kpi-grid">
        <KpiCard
          v-for="item in mainKpis"
          :key="item.label"
          :label="item.label"
          :value="item.value"
          :unit="item.unit || ''"
          :tone="item.tone"
          :icon="item.icon || ''"
          :icon-tone="item.iconTone || 'blue'"
          :delta="item.delta || null"
          :clickable="Boolean(item.clickable)"
          @select="onKpiSelect(item)"
        />
      </div>

      <h2 class="section-heading">图表</h2>
      <div class="chart-grid">
        <ChartPanel
          chart-id="overview-risk"
          chart-type="pie"
          :option="riskOption"
          :empty="riskEmpty"
          empty-text="暂无问题数据"
          aria-label="风险构成（高风险与建议占比）"
          :table="{
            columns: [
              { key: 'name', label: '风险等级' },
              { key: 'value', label: '数量' },
            ],
            rows: [
              { name: '高风险', value: riskValues.high },
              { name: '建议', value: riskValues.suggestion },
            ],
          }"
          @chart-click="onRiskClick"
        />
        <ChartPanel
          chart-id="overview-category"
          chart-type="bar"
          :option="categoryOption"
          :empty="categoryEmpty"
          empty-text="暂无数据"
          aria-label="问题类别分布"
        />
        <ChartPanel
          chart-id="overview-trend"
          chart-type="bar"
          :option="trendOption"
          :empty="trendEmpty"
          empty-text="暂无历史巡检记录"
          aria-label="近 7 次巡检问题数趋势"
        />
        <ChartPanel
          chart-id="overview-topfiles"
          chart-type="bar"
          :option="topFilesOption"
          :empty="topFilesEmpty"
          empty-text="暂无数据"
          aria-label="问题最多的文件前 10 名"
          :table="topFilesTable"
          @chart-click="onFileClick"
        />
      </div>

      <section class="section">
        <details class="card secondary-kpis">
          <summary>其他巡检指标（{{ secondaryKpis.length }} 项）</summary>
          <div class="kpi-grid kpi-grid--compact">
            <KpiCard
              v-for="item in secondaryKpis"
              :key="item.label"
              :label="item.label"
              :value="item.value"
              :unit="item.unit || ''"
              :tone="item.tone"
              :icon="item.icon || ''"
              :icon-tone="item.iconTone || 'muted'"
              :hint="item.hint || ''"
            />
          </div>
        </details>
      </section>

      <section class="section">
        <details class="card">
          <summary>降级项与警告（{{ (snapshot?.degraded || []).length }} 项降级 / {{ (snapshot?.warnings || []).length }} 条警告）</summary>
          <ul v-if="(snapshot?.degraded || []).length">
            <li v-for="(item, index) in snapshot.degraded" :key="`d-${index}`">
              {{ item.item }}：{{ item.reason }}
            </li>
          </ul>
          <p v-else>无降级项。</p>
          <ul v-if="(snapshot?.warnings || []).length">
            <li v-for="(warning, index) in snapshot.warnings" :key="`w-${index}`">{{ warning }}</li>
          </ul>
        </details>
      </section>

      <div class="status-bar">
        <div
          v-for="item in statusBar"
          :key="item.label"
          class="status-bar__item"
          :class="item.tone ? `status-bar__item--${item.tone}` : ''"
        >
          <span class="status-bar__icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path :d="STATUS_ICONS[item.icon]" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <div class="status-bar__body">
            <span class="status-bar__label">{{ item.label }}</span>
            <span class="status-bar__value">
              {{ item.value }}
              <span v-if="item.status" class="status-bar__dot" :class="`status-bar__dot--${item.tone}`"></span>
              <span v-if="item.status" class="status-bar__status">{{ item.status }}</span>
            </span>
          </div>
        </div>
      </div>
    </template>

    <EmptyState
      v-else
      title="请选择仓库"
      description="仓库列表加载完成后将自动展示数据。"
      icon="empty"
    />
  </section>
</template>