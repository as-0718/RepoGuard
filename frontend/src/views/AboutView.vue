<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { ERROR_CODE_MESSAGES } from '@api/client.js'
import { getHealth, getIssues, getOverview } from '@api/dashboard.js'
import ChartPanel from '../components/ChartPanel.vue'
import DataTable from '../components/DataTable.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const HTTP_STATUS = {
  INVALID_QUERY_PARAM: 400,
  INVALID_REPO_PATH: 400,
  REPO_FORBIDDEN: 403,
  REPO_NOT_FOUND: 404,
  METHOD_NOT_ALLOWED: 405,
  VALIDATION_ERROR: 422,
  DASHBOARD_BUSY: 503,
  DASHBOARD_UNAVAILABLE: 503,
  DASHBOARD_TIMEOUT: 504,
  INTERNAL_ERROR: 500,
  STATIC_NOT_FOUND: 404,
  NETWORK_ERROR: '—',
  CLIENT_TIMEOUT: '—',
}

const ctx = inject('dashboardContext')

const health = ref(null)
const healthError = ref(null)
const matrixRows = ref([])
const loading = ref(true)
let controller = null
let requestSeq = 0

const repoId = computed(() => ctx?.repoId?.value || '')
const snapshotMeta = computed(() => ctx?.snapshotMeta?.value || null)
const apiStatus = computed(() => {
  if (healthError.value) return '不可用'
  if (!health.value) return '—'
  return health.value.status === 'ok' ? '正常' : '降级'
})
const engineStatus = computed(() => {
  if (healthError.value) return '不可用'
  if (!health.value) return '—'
  return health.value.engine === 'available' ? '可用' : '不可用'
})
const dbStatus = computed(() => {
  if (healthError.value) return '不可用'
  if (!health.value) return '—'
  return health.value.database === 'available' ? '已连接' : '未连接'
})
const cacheAge = computed(() =>
  typeof snapshotMeta.value?.cache_age_seconds === 'number'
    ? `${snapshotMeta.value.cache_age_seconds} 秒`
    : '—',
)

const errorCodeRows = Object.entries(ERROR_CODE_MESSAGES).map(([code, message]) => ({
  code,
  status: HTTP_STATUS[code] ?? '—',
  message,
}))

const errorCodeColumns = [
  { key: 'code', label: '错误码' },
  { key: 'status', label: 'HTTP 状态', align: 'right' },
  { key: 'message', label: '中文提示' },
]

const configRows = computed(() => [
  { name: '服务', value: health.value?.service || '—' },
  { name: '版本', value: health.value?.version || '—' },
  { name: '引擎', value: engineStatus.value },
  { name: '数据库', value: dbStatus.value },
  { name: '本地库文件', value: 'data/repoguard.db' },
  { name: '默认仓库', value: health.value?.default_repo || '—' },
  { name: '允许仓库根数', value: health.value?.allowed_repo_root_count ?? '—' },
  { name: '快照 TTL（秒）', value: snapshotMeta.value?.ttl_seconds ?? '—' },
  { name: '快照扫描时间', value: snapshotMeta.value?.scanned_at || '—' },
])

const configColumns = [
  { key: 'name', label: '配置项' },
  { key: 'value', label: '值' },
]

const matrixEmpty = computed(() =>
  matrixRows.value.every((row) => Number(row.high || 0) + Number(row.suggestion || 0) === 0),
)

function heatColor(value) {
  if (value <= 0) return '#eef1f6'
  if (value < 3) return '#fbd38d'
  if (value < 8) return '#f6ad55'
  return '#c0392b'
}

const matrixOption = computed(() => {
  const cells = []
  matrixRows.value.forEach((row, rowIndex) => {
    const high = Number(row.high || 0)
    const suggestion = Number(row.suggestion || 0)
    cells.push({ value: [0, rowIndex, high], itemStyle: { color: heatColor(high) } })
    cells.push({ value: [1, rowIndex, suggestion], itemStyle: { color: heatColor(suggestion) } })
  })
  return {
    tooltip: { position: 'top' },
    grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: ['高风险', '建议'] },
    yAxis: { type: 'category', data: matrixRows.value.map((row) => row.module) },
    series: [
      {
        name: '模块状态',
        type: 'heatmap',
        data: cells,
        label: { show: true },
        emphasis: { itemStyle: { borderColor: '#333', borderWidth: 1 } },
      },
    ],
  }
})

async function loadHealth() {
  try {
    health.value = await getHealth({ signal: controller.signal })
    healthError.value = null
  } catch (err) {
    if (err?.name === 'AbortError') return
    if (err?.status === 503) {
      health.value = { status: 'degraded', engine: 'unavailable' }
      healthError.value = null
    } else {
      health.value = null
      healthError.value = err
    }
  }
}

async function loadMatrix() {
  if (!repoId.value) return
  try {
    const payload = await getIssues({ repo: repoId.value, pageSize: 1, signal: controller.signal })
    matrixRows.value = Array.isArray(payload?.charts?.module_risk_matrix)
      ? payload.charts.module_risk_matrix
      : []
  } catch (err) {
    if (err?.name !== 'AbortError') matrixRows.value = []
  }
}

async function ensureOverview() {
  if (!repoId.value || snapshotMeta.value) return
  try {
    const payload = await getOverview({ repo: repoId.value, signal: controller.signal })
    ctx?.setSnapshotMeta?.(payload?.snapshot || null)
  } catch {
    /* 保留占位符 */
  }
}

async function load() {
  controller?.abort()
  controller = new AbortController()
  const seq = ++requestSeq
  loading.value = true
  await Promise.all([loadHealth(), loadMatrix(), ensureOverview()])
  if (seq === requestSeq) loading.value = false
}

watch(
  repoId,
  () => {
    load()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  controller?.abort()
})
</script>

<template>
  <section>
    <h1 class="page-title">关于 / 健康</h1>
    <p class="page-subtitle">服务健康、数据库连接、缓存年龄、来源模块状态与错误码说明。</p>
    <p class="page-subtitle">健康检查接口：/api/health（只读）；巡检快照与修复记录保存在本地 SQLite，可在历史记录页追溯。</p>

    <LoadingSkeleton v-if="loading && !health" variant="kpi" :count="3" />

    <template v-else>
      <div v-if="healthError" class="notice notice--degraded" role="status">
        /api/health 不可用：{{ healthError.message || '请求失败' }}
      </div>

      <div class="kpi-grid">
        <KpiCard label="API 状态" :value="apiStatus" tone="neutral" />
        <KpiCard label="引擎可用性" :value="engineStatus" tone="neutral" />
        <KpiCard label="缓存年龄" :value="cacheAge" tone="muted" />
      </div>

      <div class="chart-grid chart-grid--single">
        <ChartPanel
          chart-id="about-module-status"
          chart-type="heatmap"
          :option="matrixOption"
          :empty="matrixEmpty"
          empty-text="暂无来源模块状态数据"
          aria-label="来源模块与风险等级强度热力图"
        />
      </div>

      <section class="section">
        <h2 class="section-heading">错误码矩阵</h2>
        <DataTable
          caption="错误码与中文提示对照表"
          :columns="errorCodeColumns"
          :rows="errorCodeRows"
          row-key="code"
          :page="1"
          :page-size="errorCodeRows.length"
          :total="errorCodeRows.length"
          :page-size-options="[errorCodeRows.length]"
          empty-text="暂无错误码"
        />
      </section>

      <section class="section">
        <h2 class="section-heading">版本与配置摘要</h2>
        <DataTable
          caption="版本与配置摘要（脱敏）"
          :columns="configColumns"
          :rows="configRows"
          row-key="name"
          :page="1"
          :page-size="configRows.length"
          :total="configRows.length"
          :page-size-options="[configRows.length]"
          empty-text="暂无配置信息"
        />
      </section>

      <section class="section card">
        <h2 class="section-heading">只读说明</h2>
        <ul>
          <li>看板浏览与查询均为只读；文件修复需先预览补丁、自动备份，再由用户确认后写入。</li>
          <li>历次巡检快照、问题明细与修复/回滚记录保存在本地 SQLite，历史记录页可查看趋势与修复案例；缓存过期后重新扫描。</li>
          <li>数据来源：本地巡检引擎、README 扫描器、看板快照缓存与本地 SQLite 记录库。</li>
          <li>刷新受服务端节流限制，频繁刷新会返回最近一次快照。</li>
        </ul>
      </section>
    </template>
  </section>
</template>