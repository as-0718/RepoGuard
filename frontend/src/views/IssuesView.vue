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

const MODULE_DESC = {
  命名与目录检查: '检查文件名、目录名是否规范，以及源码、文档、测试文件是否放在约定目录。',
  代码检查: '检查 Python/C 源码的注释完整性、危险函数、命令注入、裸异常、死循环、常见 bug 写法与调试残留。',
  链接检查: '检查 Markdown 链接是否可解析、路径是否有效，以及绝对路径、空格、中文等协作隐患。',
  敏感信息与大文件检查: '排查私钥、令牌、明文口令等敏感信息，并提示体积过大的文件。',
  报告: 'README 与演示项目识别相关的检查结果。',
}

const RULE_GLOSSARY = [
  { rule: 'code-001', level: '建议', desc: '模块开头缺少用途说明注释' },
  { rule: 'code-002', level: '必须', desc: '公开函数缺少参数与用途注释' },
  { rule: 'code-003', level: '建议', desc: '内部短函数缺少用途说明' },
  { rule: 'code-004', level: '必须', desc: 'C 代码使用 gets/strcpy/strcat/sprintf 等危险函数' },
  { rule: 'code-005', level: '必须', desc: '使用 eval/exec 等动态执行' },
  { rule: 'code-006', level: '必须', desc: '拼接命令或 shell=True，存在命令注入风险' },
  { rule: 'code-007', level: '建议', desc: '死循环、裸 except 或含义不明的魔法数字' },
  { rule: 'code-008', level: '建议', desc: '文件过大跳过检查，或扫描超出预算' },
  { rule: 'code-009', level: '建议', desc: '注释中遗留 TODO/FIXME/HACK/XXX 标记' },
  { rule: 'code-010', level: '建议', desc: '残留 breakpoint/pdb 调试断点' },
  { rule: 'code-011', level: '建议', desc: '可变对象作为默认参数，多次调用会共享同一对象' },
  { rule: 'code-012', level: '建议', desc: '用 ==/!= 比较 None，应使用 is / is not' },
  { rule: 'code-013', level: '建议', desc: '函数体为空（仅 pass 或 ...），缺少实际实现' },
  { rule: 'sens-001', level: '建议', desc: '文件体积超过 1MB，会拖慢仓库克隆' },
  { rule: 'sens-002', level: '必须', desc: '文件体积超过 5MB 上限' },
  { rule: 'sens-003', level: '必须', desc: '检测到 PEM 私钥内容' },
  { rule: 'sens-004', level: '必须', desc: '检测到疑似访问令牌或 API 密钥' },
  { rule: 'sens-005', level: '必须', desc: '检测到明文口令或数据库连接串' },
  { rule: 'sens-006', level: '建议', desc: '检测到较长随机字符串，可能为密钥' },
  { rule: 'sens-007', level: '建议', desc: '文件过大，敏感信息扫描可能不完整' },
  { rule: 'link-001', level: '必须', desc: '链接目标为空，点击无法跳转' },
  { rule: 'link-002', level: '必须', desc: '链接缺少右括号，Markdown 结构不完整' },
  { rule: 'link-003', level: '必须', desc: '引用式链接标识在全文没有定义' },
  { rule: 'link-004', level: '建议', desc: '使用本机绝对路径，其他设备上会失效' },
  { rule: 'link-005', level: '必须', desc: '目标含空格且未用尖括号包裹，可能解析失败' },
  { rule: 'link-006', level: '建议', desc: 'http/内网地址或缺链接文字，影响协作访问' },
  { rule: 'link-007', level: '建议', desc: '目标含中文或指向仓库外，跨设备可能失效' },
  { rule: 'link-008', level: '建议', desc: '单文件链接数量过多，建议拆分文档' },
  { rule: 'naming-001', level: '必须', desc: '文件名含系统不允许的特殊字符或结尾点' },
  { rule: 'naming-002', level: '必须', desc: '文件名长度超过 120 字符上限' },
  { rule: 'naming-003', level: '建议', desc: '文件名风格不统一，推荐小写英文加下划线' },
  { rule: 'naming-004', level: '建议', desc: '文件名或路径包含中文' },
  { rule: 'naming-005', level: '必须', desc: '源码/文档/测试文件目录归属不符合约定' },
  { rule: 'naming-006', level: '建议', desc: '文件所在目录与目录约定不一致' },
]

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

function onApplied() {
  if (ctx?.requestRefresh) {
    ctx.requestRefresh()
  } else {
    load()
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
    <p class="page-subtitle">判定口径：高风险表示可能导致崩溃、命令注入、敏感信息泄露或链接无法解析，需优先处理；建议表示可读性、规范性或协作便利性优化，可择机改进。</p>

    <section class="module-guide" aria-label="模块作用说明">
      <dl>
        <div v-for="name in MODULE_OPTIONS" :key="name">
          <dt>{{ name }}</dt>
          <dd>{{ MODULE_DESC[name] }}</dd>
        </div>
      </dl>
    </section>

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

      <p class="chart-note">命中次数：当前筛选结果中该规则检出的问题条数；点击规则柱条可按规则号筛选。</p>

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
          <FixPreviewDialog :issue="row" :repo-id="repoId" @applied="onApplied" />
        </template>
      </DataTable>

      <section class="section glossary">
        <h2 class="section-heading">规则编号释义</h2>
        <table class="data-table glossary-table">
          <thead>
            <tr>
              <th scope="col">规则编号</th>
              <th scope="col">级别</th>
              <th scope="col">含义</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in RULE_GLOSSARY" :key="row.rule">
              <td>{{ row.rule }}</td>
              <td>
                <span class="badge" :class="row.level === '必须' ? 'badge--high' : 'badge--suggestion'">
                  {{ row.level }}
                </span>
              </td>
              <td>{{ row.desc }}</td>
            </tr>
          </tbody>
        </table>
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

<style scoped>
.module-guide {
  margin: 0 0 16px;
  padding: 12px 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
}

.module-guide dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px 18px;
  margin: 0;
}

.module-guide dt {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 2px;
}

.module-guide dd {
  margin: 0;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 1.5;
}

.chart-note {
  margin: 4px 0 16px;
  color: var(--color-muted);
  font-size: 12px;
}

.glossary {
  margin-top: 24px;
}

.glossary-table {
  width: 100%;
  font-size: 13px;
}

.glossary-table td:first-child {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: nowrap;
}
</style>