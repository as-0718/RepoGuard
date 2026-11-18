<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getIssues } from '@api/dashboard.js'
import ChartPanel from '../components/ChartPanel.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import FilterBar from '../components/FilterBar.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import FixPreviewDialog from '../components/FixPreviewDialog.vue'

const DEFAULT_PAGE_SIZE = 20
const MAX_KEYWORD_LENGTH = 64
const MODULE_OPTIONS = ['命名与目录检查', '代码检查', '链接检查', '敏感信息与大文件检查', '报告']

const ctx = inject('dashboardContext')
const route = useRoute()
const router = useRouter()

const data = ref(null)
const loading = ref(false)
const error = ref(null)
let controller = null
let requestSeq = 0
let keywordTimer = null

function asText(value) {
  if (Array.isArray(value)) return value.length ? String(value[0]) : ''
  return value === undefined || value === null ? '' : String(value)
}

function asPositiveInt(value, fallback) {
  const parsed = Number.parseInt(asText(value), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function readQuery() {
  const query = route.query
  return {
    riskLevel: asText(query.risk_level) || 'all',
    sourceModule: asText(query.source_module) || 'all',
    keyword: asText(query.keyword),
    page: asPositiveInt(query.page, 1),
    pageSize: asPositiveInt(query.page_size, DEFAULT_PAGE_SIZE),
    sort: asText(query.sort) || 'risk_level',
    order: asText(query.order) === 'desc' ? 'desc' : 'asc',
  }
}

const repoId = computed(() => ctx?.repoId?.value || '')
const filters = ref(readQuery())
const counts = computed(() => data.value?.counts || {})
const ruleRows = computed(() =>
  Array.isArray(data.value?.charts?.rule_breakdown) ? data.value.charts.rule_breakdown : [],
)
const matrixRows = computed(() =>
  Array.isArray(data.value?.charts?.module_risk_matrix) ? data.value.charts.module_risk_matrix : [],
)

const totalEmpty = computed(() => Boolean(data.value) && Number(data.value.total || 0) === 0)
const ruleEmpty = computed(() => ruleRows.value.length === 0)
const matrixEmpty = computed(() =>
  matrixRows.value.every((row) => Number(row.high || 0) + Number(row.suggestion || 0) === 0),
)

const columns = [
  { key: 'file_path', label: '文件', sortable: true },
  { key: 'line_no', label: '行号', sortable: true, align: 'right' },
  { key: 'rule_id', label: '规则', sortable: true },
  { key: 'source_module', label: '模块', sortable: true },
  { key: 'risk_level', label: '风险', sortable: true },
  { key: 'message', label: '描述', sortable: true },
]

const ruleOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 24, top: 12, bottom: 8, containLabel: true },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: {
    type: 'category',
    inverse: true,
    data: ruleRows.value.map((row) => row.rule_id),
    axisLabel: { width: 160, overflow: 'truncate' },
  },
  series: [
    {
      name: '命中次数',
      type: 'bar',
      data: ruleRows.value.map((row) => Number(row.count || 0)),
      itemStyle: { color: '#1f6feb' },
    },
  ],
}))

const matrixOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0 },
  grid: { left: 8, right: 16, top: 12, bottom: 36, containLabel: true },
  xAxis: {
    type: 'category',
    data: matrixRows.value.map((row) => row.module),
    axisLabel: { interval: 0, width: 110, overflow: 'truncate' },
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '高风险',
      type: 'bar',
      stack: 'risk',
      data: matrixRows.value.map((row) => Number(row.high || 0)),
      itemStyle: { color: '#c0392b' },
    },
    {
      name: '建议',
      type: 'bar',
      stack: 'risk',
      data: matrixRows.value.map((row) => Number(row.suggestion || 0)),
      itemStyle: { color: '#b7791f' },
    },
  ],
}))

function toRouteQuery(next) {
  const query = {}
  if (repoId.value) query.repo = repoId.value
  if (next.riskLevel !== 'all') query.risk_level = next.riskLevel
  if (next.sourceModule !== 'all') query.source_module = next.sourceModule
  if (next.keyword) query.keyword = next.keyword
  if (next.page > 1) query.page = String(next.page)
  if (next.pageSize !== DEFAULT_PAGE_SIZE) query.page_size = String(next.pageSize)
  if (next.sort !== 'risk_level') query.sort = next.sort
  if (next.order !== 'asc') query.order = next.order
  return query
}

function applyQuery(partial) {
  router.replace({ query: toRouteQuery({ ...readQuery(), ...partial }) })
}

function onFiltersUpdate(next) {
  const prev = filters.value
  filters.value = { ...next }
  if (next.riskLevel !== prev.riskLevel || next.sourceModule !== prev.sourceModule) {
    if (keywordTimer) clearTimeout(keywordTimer)
    keywordTimer = null
    applyQuery({
      riskLevel: next.riskLevel,
      sourceModule: next.sourceModule,
      keyword: next.keyword,
      page: 1,
    })
    return
  }
  if (next.keyword !== prev.keyword) {
    if (keywordTimer) clearTimeout(keywordTimer)
    keywordTimer = setTimeout(() => {
      keywordTimer = null
      applyQuery({ keyword: next.keyword, page: 1 })
    }, 300)
  }
}

function onSubmit() {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = null
  applyQuery({ ...filters.value, page: 1 })
}

function onReset() {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = null
  filters.value = { riskLevel: 'all', sourceModule: 'all', keyword: '' }
  router.replace({ query: { repo: repoId.value || undefined } })
}

function onSortChange({ field, order }) {
  applyQuery({ sort: field, order, page: 1 })
}

function onPageChange({ page, pageSize }) {
  applyQuery({ page, pageSize })
}

function onRuleClick({ name }) {
  if (!name) return
  filters.value = { ...filters.value, keyword: String(name).slice(0, MAX_KEYWORD_LENGTH) }
  applyQuery({ keyword: String(name).slice(0, MAX_KEYWORD_LENGTH), page: 1 })
}

function clearRefreshParam() {
  if (!('refresh' in route.query) && !('_r' in route.query)) return
  const query = { ...route.query }
  delete query.refresh
  delete query._r
  router.replace({ query })
}

async function load() {
  const repo = repoId.value
  if (!repo) return
  const current = readQuery()
  const forceRefresh = asText(route.query.refresh) === '1'
  controller?.abort()
  controller = new AbortController()
  const seq = ++requestSeq
  loading.value = true
  ctx?.setRequesting?.(true)
  error.value = null
  try {
    const payload = await getIssues({
      repo,
      refresh: forceRefresh,
      riskLevel: current.riskLevel,
      sourceModule: current.sourceModule,
      keyword: current.keyword,
      page: current.page,
      pageSize: current.pageSize,
      sort: current.sort,
      order: current.order,
      signal: controller.signal,
    })
    if (seq !== requestSeq) return
    data.value = payload
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

const requestKey = computed(() => {
  const current = readQuery()
  return [
    repoId.value,
    ctx?.refreshTick?.value ?? 0,
    current.riskLevel,
    current.sourceModule,
    current.keyword,
    current.page,
    current.pageSize,
    current.sort,
    current.order,
  ].join('|')
})

watch(requestKey, () => load(), { immediate: true })

watch(
  () => route.query,
  () => {
    filters.value = readQuery()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  requestSeq += 1
  controller?.abort()
  if (keywordTimer) clearTimeout(keywordTimer)
  ctx?.setRequesting?.(false)
})
</script>

<template>
  <section>
    <h1 class="page-title">问题明细</h1>
    <p class="page-subtitle">按风险等级、来源模块与关键词筛选巡检问题；筛选条件写入地址栏。</p>

    <FilterBar
      :model-value="filters"
      :module-options="MODULE_OPTIONS"
      :disabled="loading || !repoId"
      :max-keyword-length="MAX_KEYWORD_LENGTH"
      @update:model-value="onFiltersUpdate"
      @submit="onSubmit"
      @reset="onReset"
    />

    <LoadingSkeleton v-if="loading && !data" variant="kpi" :count="3" />

    <template v-else-if="error && !data">
      <ErrorBanner :error="error" @retry="load" />
      <EmptyState title="暂无可用数据" description="请确认后端服务已启动，并选择可用仓库。" icon="no-data" />
    </template>

    <template v-else-if="data">
      <div v-if="loading" class="progress-line" aria-hidden="true"></div>
      <ErrorBanner :error="error" :stale="true" @retry="load" />

      <div class="kpi-grid">
        <KpiCard label="筛选后总数" :value="counts.total || 0" tone="neutral" />
        <KpiCard label="高风险" :value="counts.high || 0" tone="high" />
        <KpiCard label="建议" :value="counts.suggestion || 0" tone="suggestion" />
      </div>

      <div class="chart-grid">
        <ChartPanel
          chart-id="issues-rule"
          chart-type="bar"
          :option="ruleOption"
          :empty="ruleEmpty"
          empty-text="暂无规则命中数据"
          aria-label="命中次数最多的规则前 10 名"
          @chart-click="onRuleClick"
        />
        <ChartPanel
          chart-id="issues-matrix"
          chart-type="bar"
          :option="matrixOption"
          :empty="matrixEmpty"
          empty-text="暂无模块分布数据"
          aria-label="来源模块与风险等级分布"
        />
      </div>

      <EmptyState
        v-if="totalEmpty"
        title="没有符合条件的问题"
        description="可调整风险等级、来源模块或关键词后重试。"
        icon="no-issue"
      />
      <DataTable
        v-else
        caption="问题明细表"
        :columns="columns"
        :rows="data.items || []"
        row-key="file_path"
        :sort="readQuery().sort"
        :order="readQuery().order"
        :page="readQuery().page"
        :page-size="readQuery().pageSize"
        :total="data.total || 0"
        :page-size-options="[20, 50, 100]"
        empty-text="暂无数据"
        expandable
        @sort-change="onSortChange"
        @page-change="onPageChange"
      >
        <template #detail="{ row }">
          <dl>
            <dt>建议</dt>
            <dd>{{ row.suggestion || '—' }}</dd>
            <dt>片段</dt>
            <dd>{{ row.excerpt || '—' }}</dd>
          </dl>
          <FixPreviewDialog :issue="row" :repo-id="repoId" @applied="load" />
        </template>
      </DataTable>
    </template>

    <EmptyState
      v-else
      title="请选择仓库"
      description="仓库列表加载完成后将自动展示数据。"
      icon="empty"
    />
  </section>
</template>