<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  caption: { type: String, default: '数据表' },
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: 'id' },
  sort: { type: String, default: '' },
  order: { type: String, default: 'asc' },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  pageSizeOptions: { type: Array, default: () => [20, 50, 100] },
  emptyText: { type: String, default: '暂无数据' },
  expandable: { type: Boolean, default: false },
})

const emit = defineEmits(['sort-change', 'page-change', 'row-toggle'])

const expanded = ref(new Set())

const totalPages = computed(() => {
  if (!props.total || !props.pageSize) return 0
  return Math.ceil(props.total / props.pageSize)
})

const currentPage = computed(() => {
  if (!totalPages.value) return 1
  return Math.min(Math.max(1, props.page), totalPages.value)
})

watch(
  () => props.rows,
  () => {
    expanded.value = new Set()
  },
)

function keyOf(row, index) {
  const value = row?.[props.rowKey]
  return value === undefined || value === null ? `row-${index}` : `${value}#${index}`
}

function isExpanded(row, index) {
  return expanded.value.has(keyOf(row, index))
}

function toggle(row, index) {
  const key = keyOf(row, index)
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
  emit('row-toggle', row)
}

function ariaSort(column) {
  if (!column.sortable) return undefined
  if (props.sort !== column.key) return 'none'
  return props.order === 'desc' ? 'descending' : 'ascending'
}

function sortIndicator(column) {
  if (props.sort !== column.key) return '↕'
  return props.order === 'desc' ? '↓' : '↑'
}

function onSort(column) {
  if (!column.sortable) return
  const nextOrder = props.sort === column.key && props.order === 'asc' ? 'desc' : 'asc'
  emit('sort-change', { field: column.key, order: nextOrder })
}

function onPage(nextPage) {
  const target = Math.min(Math.max(1, nextPage), totalPages.value || 1)
  if (target === props.page) return
  emit('page-change', { page: target, pageSize: props.pageSize })
}

function onPageSize(event) {
  emit('page-change', { page: 1, pageSize: Number(event.target.value) })
}

function cellText(row, column) {
  const value = row?.[column.key]
  if (value === undefined || value === null || value === '') return '—'
  return String(value)
}

function riskText(row) {
  const value = row?.risk_level
  if (value === 'high' || value === '高风险') return '高风险'
  if (value === 'suggestion' || value === '建议') return '建议'
  return value || '—'
}

function riskClass(row) {
  const value = row?.risk_level
  if (value === 'high' || value === '高风险') return 'badge--high'
  if (value === 'suggestion' || value === '建议') return 'badge--suggestion'
  return 'badge--neutral'
}
</script>

<template>
  <div class="table-wrap">
    <table class="data-table">
      <caption>{{ caption }}</caption>
      <thead>
        <tr>
          <th v-if="expandable" scope="col"><span class="sr-only">展开详情</span></th>
          <th
            v-for="column in columns"
            :key="column.key"
            scope="col"
            :aria-sort="ariaSort(column)"
            :class="{ 'data-table__cell--num': column.align === 'right' }"
          >
            <button
              v-if="column.sortable"
              type="button"
              class="data-table__sort"
              @click="onSort(column)"
            >
              {{ column.label }}
              <span aria-hidden="true">{{ sortIndicator(column) }}</span>
            </button>
            <template v-else>{{ column.label }}</template>
          </th>
        </tr>
      </thead>

      <tbody v-if="rows.length">
        <template v-for="(row, index) in rows" :key="keyOf(row, index)">
          <tr>
            <td v-if="expandable">
              <button
                type="button"
                class="data-table__expand"
                :aria-expanded="isExpanded(row, index)"
                @click="toggle(row, index)"
              >
                {{ isExpanded(row, index) ? '收起' : '展开' }}
              </button>
            </td>
            <td
              v-for="column in columns"
              :key="column.key"
              :class="{ 'data-table__cell--num': column.align === 'right' }"
            >
              <span v-if="column.key === 'risk_level'" class="badge" :class="riskClass(row)">
                {{ riskText(row) }}
              </span>
              <template v-else>{{ cellText(row, column) }}</template>
            </td>
          </tr>
          <tr v-if="expandable && isExpanded(row, index)" class="data-table__detail">
            <td :colspan="columns.length + 1">
              <slot name="detail" :row="row">—</slot>
            </td>
          </tr>
        </template>
      </tbody>

      <tbody v-else>
        <tr>
          <td :colspan="columns.length + (expandable ? 1 : 0)">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="totalPages > 0" class="pager">
      <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total.toLocaleString('zh-CN') }} 条</span>
      <button type="button" class="btn" :disabled="currentPage <= 1" @click="onPage(props.page - 1)">
        上一页
      </button>
      <button
        type="button"
        class="btn"
        :disabled="currentPage >= totalPages"
        @click="onPage(props.page + 1)"
      >
        下一页
      </button>
      <label>
        每页
        <select :value="pageSize" @change="onPageSize">
          <option v-for="option in pageSizeOptions" :key="option" :value="option">{{ option }}</option>
        </select>
        条
      </label>
    </div>
  </div>
</template>