<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getOverview } from '@api/dashboard.js'
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

const moduleRows = computed(() =>
  Array.isArray(charts.value.module_breakdown) ? charts.value.module_breakdown : [],
)
const fileTypeRows = computed(() =>
  Array.isArray(charts.value.file_type_breakdown) ? charts.value.file_type_breakdown : [],
)
const topFileRows = computed(() => (Array.isArray(charts.value.top_files) ? charts.value.top_files : []))

const FILE_TYPE_LABELS = { markdown: '文档', code: '代码', other: '其他' }

const hasDegraded = computed(() => {
  const meta = snapshot.value
  return Boolean(meta && (meta.status === '部分降级' || (meta.degraded || []).length > 0))
})

const riskEmpty = computed(() => riskValues.value.high + riskValues.value.suggestion === 0)
const moduleEmpty = computed(() => moduleRows.value.every((row) => Number(row.count || 0) === 0))
const fileTypeEmpty = computed(() => fileTypeRows.value.every((row) => Number(row.count || 0) === 0))
const topFilesEmpty = computed(() => topFileRows.value.length === 0)

const riskOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
  legend: { bottom: 0 },
  series: [
    {
      name: '风险构成',
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      data: [
        { name: '高风险', value: riskValues.value.high, itemStyle: { color: '#c0392b' } },
        { name: '建议', value: riskValues.value.suggestion, itemStyle: { color: '#b7791f' } },
      ],
      label: { formatter: '{b}：{c}' },
    },
  ],
}))

const moduleOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 24, top: 12, bottom: 8, containLabel: true },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: { type: 'category', inverse: true, data: moduleRows.value.map((row) => row.module) },
  series: [
    {
      name: '问题数',
      type: 'bar',
      data: moduleRows.value.map((row) => Number(row.count || 0)),
      itemStyle: { color: '#1f6feb' },
    },
  ],
}))

const fileTypeOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
  xAxis: {
    type: 'category',
    data: fileTypeRows.value.map((row) => FILE_TYPE_LABELS[row.type] || row.type),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '文件数',
      type: 'bar',
      data: fileTypeRows.value.map((row) => Number(row.count || 0)),
      itemStyle: { color: '#2f855a' },
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
      data: topFileRows.value.map((row) => Number(row.issue_count || 0)),
      itemStyle: { color: '#6b46c1' },
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

const kpiItems = computed(() => [
  { label: '文件数', value: data.value?.files_count, tone: 'neutral' },
  { label: '问题总数', value: summary.value.issue_count, tone: 'neutral' },
  { label: '高风险', value: summary.value.must_fix_count, tone: 'high', clickable: true },
  { label: '建议', value: summary.value.suggestion_count, tone: 'suggestion', clickable: true },
  { label: '僵尸候选', value: summary.value.zombie_candidate_count, tone: 'neutral' },
  { label: '无法判定', value: summary.value.undetermined_count, tone: 'muted' },
  { label: '降级项', value: summary.value.degraded_count, tone: 'muted' },
  { label: '跳过文件', value: summary.value.skipped_file_count, tone: 'muted' },
  { label: '扫描耗时', value: snapshot.value?.duration_ms, unit: 'ms', tone: 'neutral' },
])

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
    const payload = await getOverview({
      repo,
      refresh: forceRefresh,
      signal: controller.signal,
    })
    if (seq !== requestSeq) return
    data.value = payload
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

function onModuleClick({ name }) {
  if (name) goIssues({ source_module: name })
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
          v-for="item in kpiItems"
          :key="item.label"
          :label="item.label"
          :value="item.value"
          :unit="item.unit || ''"
          :tone="item.tone"
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
          chart-id="overview-module"
          chart-type="bar"
          :option="moduleOption"
          :empty="moduleEmpty"
          empty-text="暂无数据"
          aria-label="来源模块分布"
          @chart-click="onModuleClick"
        />
        <ChartPanel
          chart-id="overview-filetype"
          chart-type="bar"
          :option="fileTypeOption"
          :empty="fileTypeEmpty"
          empty-text="暂无数据"
          aria-label="文件类型分布"
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
    </template>

    <EmptyState
      v-else
      title="请选择仓库"
      description="仓库列表加载完成后将自动展示数据。"
      icon="empty"
    />
  </section>
</template>