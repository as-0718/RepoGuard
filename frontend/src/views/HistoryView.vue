<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { getHistory, getHistoryDetail } from '@api/dashboard.js'
import ChartPanel from '../components/ChartPanel.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const ctx = inject('dashboardContext')

const history = ref([])
const loading = ref(false)
const error = ref(null)
const details = ref({})

let controller = null
let requestSeq = 0
let lastTick = 0

const repoId = computed(() => ctx?.repoId?.value || '')
const trendRows = computed(() => [...history.value].reverse())
const trendEmpty = computed(() => trendRows.value.length === 0)

function shortTime(value) {
  if (!value) return '—'
  const text = String(value)
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text
}

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0 },
  grid: { left: 8, right: 16, top: 12, bottom: 28, containLabel: true },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: trendRows.value.map((row) => shortTime(row.scanned_at)),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '问题总数',
      type: 'line',
      smooth: true,
      data: trendRows.value.map((row) => Number(row.issue_count || 0)),
      itemStyle: { color: '#1f6feb' },
    },
    {
      name: '高风险',
      type: 'line',
      smooth: true,
      data: trendRows.value.map((row) => Number(row.must_fix_count || 0)),
      itemStyle: { color: '#c0392b' },
    },
    {
      name: '建议',
      type: 'line',
      smooth: true,
      data: trendRows.value.map((row) => Number(row.suggestion_count || 0)),
      itemStyle: { color: '#b7791f' },
    },
  ],
}))

const snapshotColumns = [
  { key: 'scanned_at', label: '扫描时间' },
  { key: 'files_count', label: '文件数', align: 'right' },
  { key: 'issue_count', label: '问题总数', align: 'right' },
  { key: 'must_fix_count', label: '高风险', align: 'right' },
  { key: 'suggestion_count', label: '建议', align: 'right' },
  { key: 'zombie_count', label: '僵尸候选', align: 'right' },
  { key: 'undetermined_count', label: '无法判定', align: 'right' },
  { key: 'duration_ms', label: '耗时(ms)', align: 'right' },
]

const issueColumns = [
  { key: 'file_path', label: '文件路径' },
  { key: 'line_no', label: '行号' },
  { key: 'rule_id', label: '规则' },
  { key: 'source_module', label: '模块' },
  { key: 'risk_level', label: '级别' },
  { key: 'message', label: '问题描述' },
  { key: 'suggestion', label: '修改建议' },
]

function detailOf(row) {
  return details.value[row?.id] || null
}

async function load() {
  const repo = repoId.value
  if (!repo) return
  controller?.abort()
  controller = new AbortController()
  const seq = ++requestSeq
  loading.value = true
  ctx?.setRequesting?.(true)
  error.value = null
  try {
    const payload = await getHistory({ repo, limit: 20, signal: controller.signal })
    if (seq !== requestSeq) return
    history.value = Array.isArray(payload?.history) ? payload.history : []
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

async function ensureDetail(row) {
  const id = row?.id
  if (!id || details.value[id]) return
  details.value = { ...details.value, [id]: { status: 'loading', detail: null, error: '' } }
  try {
    const payload = await getHistoryDetail({ id, signal: controller?.signal })
    details.value = { ...details.value, [id]: { status: 'loaded', detail: payload?.snapshot || null, error: '' } }
  } catch (err) {
    details.value = {
      ...details.value,
      [id]: { status: 'error', detail: null, error: err?.message || '加载明细失败' },
    }
  }
}

function onRowToggle(row) {
  ensureDetail(row)
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
    <h1 class="page-title">历史记录</h1>
    <p class="page-subtitle">本地 SQLite 保存的历次巡检快照，用于观察问题数量随时间的变化趋势。</p>

    <LoadingSkeleton v-if="loading && !history.length" variant="kpi" :count="4" />

    <template v-else-if="error && !history.length">
      <ErrorBanner :error="error" @retry="load" />
      <EmptyState
        title="暂无可用数据"
        description="请确认后端服务已启动，并在上方选择可用仓库。"
        icon="no-data"
      />
    </template>

    <template v-else>
      <div v-if="loading" class="progress-line" aria-hidden="true"></div>
      <ErrorBanner :error="error" :stale="true" @retry="load" />

      <ChartPanel
        chart-id="history-trend"
        chart-type="line"
        :option="trendOption"
        :empty="trendEmpty"
        empty-text="暂无历史趋势数据"
        aria-label="历次巡检问题数量趋势"
        height="300px"
      />

      <DataTable
        caption="历史巡检快照"
        :columns="snapshotColumns"
        :rows="history"
        row-key="id"
        :expandable="true"
        empty-text="暂无历史记录，完成一次巡检后会自动保存。"
        @row-toggle="onRowToggle"
      >
        <template #detail="{ row }">
          <div class="history-detail">
            <template v-if="detailOf(row)?.status === 'loading'">
              <p class="history-detail__hint">正在加载本次问题明细…</p>
            </template>
            <template v-else-if="detailOf(row)?.status === 'error'">
              <p class="history-detail__hint history-detail__hint--high">
                {{ detailOf(row).error || '明细加载失败' }}
              </p>
            </template>
            <template v-else-if="detailOf(row)?.detail">
              <table class="data-table history-detail__table">
                <thead>
                  <tr>
                    <th v-for="column in issueColumns" :key="column.key" scope="col">{{ column.label }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(issue, index) in detailOf(row).detail.issues || []" :key="index">
                    <td>{{ issue.file_path || '—' }}</td>
                    <td>{{ issue.line_no ?? '—' }}</td>
                    <td>{{ issue.rule_id || '—' }}</td>
                    <td>{{ issue.source_module || '—' }}</td>
                    <td>{{ issue.risk_level || '—' }}</td>
                    <td>{{ issue.message || '—' }}</td>
                    <td>{{ issue.suggestion || '—' }}</td>
                  </tr>
                  <tr v-if="!(detailOf(row).detail.issues || []).length">
                    <td :colspan="issueColumns.length">本次巡检无问题明细。</td>
                  </tr>
                </tbody>
              </table>
            </template>
            <template v-else>
              <p class="history-detail__hint">展开后加载本次问题明细。</p>
            </template>
          </div>
        </template>
      </DataTable>
    </template>
  </section>
</template>

<style scoped>
.history-detail {
  padding: 8px 0;
}

.history-detail__hint {
  margin: 0;
  color: var(--color-muted);
  font-size: 14px;
}

.history-detail__hint--high {
  color: var(--color-high);
}

.history-detail__table {
  width: 100%;
  font-size: 13px;
}
</style>
