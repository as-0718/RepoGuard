<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { getFixEvents, getHistory, getHistoryDetail } from '@api/dashboard.js'
import ChartPanel from '../components/ChartPanel.vue'
import DataTable from '../components/DataTable.vue'
import KpiCard from '../components/KpiCard.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const ctx = inject('dashboardContext')

const history = ref([])
const totalCount = ref(0)
const loading = ref(false)
const error = ref(null)
const details = ref({})
const fixEvents = ref([])
const fixError = ref(null)

const ACTION_LABEL = { apply: '应用修复', rollback: '回滚恢复' }
const RESULT_LABEL = { success: '成功', partial: '部分成功', failed: '失败' }
const RESULT_CLASS = {
  success: 'fix-badge--success',
  partial: 'badge--suggestion',
  failed: 'badge--high',
}

function actionLabel(row) {
  return ACTION_LABEL[row?.action] || row?.action || '—'
}

function resultLabel(row) {
  return RESULT_LABEL[row?.result] || row?.result || '—'
}

function resultClass(row) {
  return RESULT_CLASS[row?.result] || 'badge--neutral'
}

function fileLabel(file) {
  if (typeof file === 'string') return file
  const path = file?.path || '—'
  const mtime = shortTime(file?.mtime)
  return mtime && mtime !== '—' ? `${path}（${mtime}）` : path
}

function filesText(row) {
  const files = Array.isArray(row?.files) ? row.files : []
  return files.length ? files.map(fileLabel).join('、') : '—'
}

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
      itemStyle: { color: '#2c7ceb' },
    },
    {
      name: '高风险',
      type: 'line',
      smooth: true,
      data: trendRows.value.map((row) => Number(row.must_fix_count || 0)),
      itemStyle: { color: '#e56159' },
    },
    {
      name: '建议',
      type: 'line',
      smooth: true,
      data: trendRows.value.map((row) => Number(row.suggestion_count || 0)),
      itemStyle: { color: '#e3b045' },
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
    totalCount.value = Number(payload?.total_count ?? history.value.length) || 0
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

async function loadFixEvents() {
  try {
    const payload = await getFixEvents({ limit: 20, signal: controller?.signal })
    fixEvents.value = Array.isArray(payload?.events) ? payload.events : []
    fixError.value = null
  } catch (err) {
    if (err?.name === 'AbortError') return
    fixError.value = {
      code: err?.code || 'NETWORK_ERROR',
      message: err?.message || '修复案例加载失败',
      detail: err?.detail || '',
    }
  }
}

watch(
  repoId,
  (repo) => {
    if (repo) {
      load(false)
      loadFixEvents()
    }
  },
  { immediate: true },
)

watch(
  () => ctx?.refreshTick?.value ?? 0,
  (tick) => {
    if (tick === lastTick) return
    lastTick = tick
    if (repoId.value) {
      load(true)
      loadFixEvents()
    }
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

      <div class="history-stats">
        <KpiCard
          label="累计巡查"
          :value="totalCount"
          unit="次"
          hint="当前仓库在本地 SQLite 库中保存的巡检快照总数，不受列表条数限制。"
        />
      </div>

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

      <section class="fix-events">
        <h2 class="section-title">修复与回滚案例</h2>
        <p class="section-subtitle">
          本地 SQLite 留存历次自动修复与回滚结果，跨会话可查；空表表示本次运行后尚未执行过修复。
        </p>
        <ErrorBanner v-if="fixError" :error="fixError" :stale="true" />
        <table class="data-table fix-events__table">
          <thead>
            <tr>
              <th scope="col">时间</th>
              <th scope="col">动作</th>
              <th scope="col">结果</th>
              <th scope="col" class="num">已修改</th>
              <th scope="col" class="num">已回滚</th>
              <th scope="col" class="num">跳过</th>
              <th scope="col" class="num">失败</th>
              <th scope="col">涉及文件</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!fixEvents.length">
              <td :colspan="8">暂无修复案例，执行一次链接修复后会自动记录。</td>
            </tr>
            <tr v-for="row in fixEvents" :key="row.id">
              <td>{{ shortTime(row.created_at) }}</td>
              <td>{{ actionLabel(row) }}</td>
              <td>
                <span class="badge" :class="resultClass(row)">{{ resultLabel(row) }}</span>
              </td>
              <td class="num">{{ row.applied_count ?? 0 }}</td>
              <td class="num">{{ row.restored_count ?? 0 }}</td>
              <td class="num">{{ row.skipped_count ?? 0 }}</td>
              <td class="num">{{ row.failed_count ?? 0 }}</td>
              <td class="fix-events__files">{{ filesText(row) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.history-stats {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

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

.fix-events {
  margin-top: 24px;
}

.section-title {
  font-size: 16px;
  margin: 0 0 4px;
}

.section-subtitle {
  color: var(--color-muted);
  font-size: 13px;
  margin: 0 0 12px;
}

.fix-events__table {
  width: 100%;
  font-size: 13px;
}

.fix-events__table .num {
  text-align: right;
}

.fix-events__files {
  max-width: 280px;
  word-break: break-all;
}

.fix-badge--success {
  color: var(--color-accent-2);
  background: var(--color-neutral-soft);
}
</style>
