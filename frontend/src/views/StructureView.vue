<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { getStructure } from '@api/dashboard.js'
import ChartPanel from '../components/ChartPanel.vue'
import DataTable from '../components/DataTable.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import KpiCard from '../components/KpiCard.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const ctx = inject('dashboardContext')

const data = ref(null)
const loading = ref(false)
const error = ref(null)
const diffFilter = ref('')
let controller = null
let requestSeq = 0
let lastTick = 0

const repoId = computed(() => ctx?.repoId?.value || '')
const readme = computed(() => data.value?.readme || {})
const index = computed(() => data.value?.index || {})
const demo = computed(() => data.value?.demo || {})
const diffs = computed(() => (Array.isArray(readme.value.diffs) ? readme.value.diffs : []))
const confirmedItems = computed(() =>
  Array.isArray(demo.value.confirmed_items) ? demo.value.confirmed_items : [],
)
const undeterminedItems = computed(() =>
  Array.isArray(readme.value.undetermined) ? readme.value.undetermined : [],
)

const docCount = computed(() => (index.value.document_section?.items || []).length)
const demoCount = computed(() => (index.value.demo_section?.items || []).length)
const suspectedCount = computed(() => Number(readme.value.demo_project_suspected_count || 0))

const diffTypes = computed(() => {
  const map = new Map()
  for (const diff of diffs.value) {
    const key = diff.change_type || '未知'
    map.set(key, (map.get(key) || 0) + 1)
  }
  return [...map.entries()].map(([type, count]) => ({ type, count }))
})

const filteredDiffs = computed(() =>
  diffFilter.value ? diffs.value.filter((diff) => diff.change_type === diffFilter.value) : diffs.value,
)

const sectionEmpty = computed(() => docCount.value + demoCount.value === 0)
const demoEmpty = computed(() => Number(readme.value.demo_project_count || 0) + suspectedCount.value === 0)
const diffEmpty = computed(() => diffTypes.value.length === 0)

const sectionsOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
  legend: { bottom: 0 },
  series: [
    {
      name: '目录分区',
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      data: [
        { name: '文档索引', value: docCount.value, itemStyle: { color: '#1f6feb' } },
        { name: 'Demo 工程', value: demoCount.value, itemStyle: { color: '#2f855a' } },
      ],
      label: { formatter: '{b}：{c}' },
    },
  ],
}))

const demoOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
  xAxis: { type: 'category', data: ['确认 Demo', '疑似 Demo'] },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '数量',
      type: 'bar',
      data: [
        Number(readme.value.demo_project_count || 0),
        suspectedCount.value,
      ],
      itemStyle: { color: '#2f855a' },
    },
  ],
}))

const diffOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
  xAxis: { type: 'category', data: diffTypes.value.map((item) => item.type) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: '差异数',
      type: 'bar',
      data: diffTypes.value.map((item) => item.count),
      itemStyle: { color: '#b7791f' },
    },
  ],
}))

const diffColumns = [
  { key: 'change_type', label: '变更类型' },
  { key: 'path', label: '路径' },
  { key: 'old_title', label: '旧标题' },
  { key: 'new_title', label: '新标题' },
  { key: 'old_position', label: '旧位置', align: 'right' },
  { key: 'new_position', label: '新位置', align: 'right' },
]

const demoColumns = [
  { key: 'path', label: '路径' },
  { key: 'title', label: '标题' },
]

const undeterminedColumns = [
  { key: 'item', label: '项目' },
  { key: 'reason', label: '原因' },
]

const kpiItems = computed(() => [
  { label: '文档数', value: readme.value.document_count || 0 },
  { label: 'Demo 确认数', value: readme.value.demo_project_count || 0 },
  { label: '疑似 Demo 数', value: suspectedCount.value },
  { label: 'README', value: readme.value.readme_found ? '已找到' : '未找到' },
  { label: '目录区块', value: readme.value.toc_block_found ? '已找到' : '未找到' },
  { label: 'README 差异数', value: diffs.value.length },
])

function onDiffTypeClick({ name }) {
  diffFilter.value = diffFilter.value === name ? '' : name
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
    const payload = await getStructure({
      repo,
      refresh: forceRefresh,
      signal: controller.signal,
    })
    if (seq !== requestSeq) return
    data.value = payload
    ctx?.setSnapshotMeta?.(payload?.snapshot || null)
    diffFilter.value = ''
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
    <h1 class="page-title">结构 / README</h1>
    <p class="page-subtitle">README 索引、文档/Demo 分区与结构差异；疑似 Demo 仅提供计数，明细需人工确认。</p>

    <LoadingSkeleton v-if="loading && !data" variant="kpi" :count="6" />

    <template v-else-if="error && !data">
      <ErrorBanner :error="error" @retry="load(false)" />
      <EmptyState title="暂无可用数据" description="请确认后端服务已启动，并选择可用仓库。" icon="no-data" />
    </template>

    <template v-else-if="data">
      <div v-if="loading" class="progress-line" aria-hidden="true"></div>
      <ErrorBanner :error="error" :stale="true" @retry="load(false)" />

      <div v-if="!readme.readme_found" class="notice notice--degraded" role="status">
        未找到 README，结构数据可能不完整。
      </div>
      <div v-if="(readme.degraded || []).length" class="notice notice--degraded" role="status">
        README 扫描部分降级：{{ readme.degraded.map((item) => item.reason).join('；') }}
      </div>

      <div class="kpi-grid">
        <KpiCard
          v-for="item in kpiItems"
          :key="item.label"
          :label="item.label"
          :value="item.value"
          tone="neutral"
        />
      </div>

      <div class="chart-grid">
        <ChartPanel
          chart-id="structure-sections"
          chart-type="pie"
          :option="sectionsOption"
          :empty="sectionEmpty"
          empty-text="暂无目录分区数据"
          aria-label="目录分区构成（文档索引与 Demo 工程）"
        />
        <ChartPanel
          chart-id="structure-demo"
          chart-type="bar"
          :option="demoOption"
          :empty="demoEmpty"
          empty-text="暂无 Demo 数据"
          aria-label="Demo 确认数与疑似数"
        />
        <ChartPanel
          chart-id="structure-diffs"
          chart-type="bar"
          :option="diffOption"
          :empty="diffEmpty"
          empty-text="暂无差异数据"
          aria-label="README 差异类型分布"
          @chart-click="onDiffTypeClick"
        />
      </div>

      <p v-if="suspectedCount > 0" class="notice" role="status">
        存在 {{ suspectedCount }} 个疑似 Demo 工程（仅计数），明细需人工确认。
      </p>

      <section class="section">
        <h2 class="section-heading">
          README 差异明细
          <span v-if="diffFilter" class="tone-tag tone-tag--muted">已筛选：{{ diffFilter }}</span>
        </h2>
        <DataTable
          v-if="filteredDiffs.length"
          caption="README 差异明细表"
          :columns="diffColumns"
          :rows="filteredDiffs"
          row-key="path"
          :page="1"
          :page-size="filteredDiffs.length || 1"
          :total="filteredDiffs.length"
          :page-size-options="[filteredDiffs.length || 1]"
          empty-text="暂无差异"
        />
        <EmptyState v-else title="暂无差异数据" description="README 与仓库结构一致。" icon="no-data" />
      </section>

      <section class="section">
        <h2 class="section-heading">Demo 清单（已确认）</h2>
        <DataTable
          v-if="confirmedItems.length"
          caption="已确认 Demo 工程清单"
          :columns="demoColumns"
          :rows="confirmedItems"
          row-key="path"
          :page="1"
          :page-size="confirmedItems.length || 1"
          :total="confirmedItems.length"
          :page-size-options="[confirmedItems.length || 1]"
          empty-text="暂无已确认 Demo"
        />
        <EmptyState v-else title="暂无已确认 Demo" description="未在 README 中识别到 Demo 工程。" icon="empty" />
      </section>

      <section class="section">
        <h2 class="section-heading">无法判定项</h2>
        <DataTable
          v-if="undeterminedItems.length"
          caption="无法判定项清单"
          :columns="undeterminedColumns"
          :rows="undeterminedItems"
          row-key="item"
          :page="1"
          :page-size="undeterminedItems.length || 1"
          :total="undeterminedItems.length"
          :page-size-options="[undeterminedItems.length || 1]"
          empty-text="暂无无法判定项"
        />
        <EmptyState v-else title="暂无无法判定项" description="所有条目均已归类。" icon="no-issue" />
      </section>

      <section class="section">
        <h2 class="section-heading">README 索引预览</h2>
        <pre class="markdown-preview">{{ readme.index_markdown || '（无 README 索引内容）' }}</pre>
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