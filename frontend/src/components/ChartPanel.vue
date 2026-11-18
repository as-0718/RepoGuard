<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, HeatmapChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DatasetComponent,
  AriaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { themeRef } from '../api/theme.js'
import { themedOption } from '../api/chartTheme.js'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DatasetComponent,
  AriaComponent,
  CanvasRenderer,
])

const props = defineProps({
  chartId: { type: String, required: true },
  chartType: { type: String, default: 'bar' },
  option: { type: Object, default: null },
  empty: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  ariaLabel: { type: String, default: '' },
  table: { type: Object, default: null },
  height: { type: String, default: '320px' },
})

const emit = defineEmits(['chart-click'])

const el = ref(null)
let chart = null
let observer = null
let resizeTimer = null

function withAria(option) {
  return { ...option, aria: { enabled: true, decal: { show: true } } }
}

function resolveOption() {
  return withAria(themedOption(props.option))
}

function handleClick(params) {
  emit('chart-click', {
    name: params?.name,
    value: params?.value,
    dataIndex: params?.dataIndex,
    seriesName: params?.seriesName,
  })
}

function ensureObserver() {
  if (observer || !el.value || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(scheduleResize)
  observer.observe(el.value)
}

function ensureInit() {
  if (chart || props.empty || !el.value) return
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  if (props.option) chart.setOption(resolveOption(), { notMerge: true })
  chart.on('click', handleClick)
  ensureObserver()
}

function disposeChart() {
  if (chart) {
    chart.off('click', handleClick)
    chart.dispose()
    chart = null
  }
  observer?.disconnect()
  observer = null
}

function scheduleResize() {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    resizeTimer = null
    chart?.resize()
  }, 100)
}

watch(
  () => props.option,
  (option) => {
    if (!option) return
    if (props.empty) {
      chart?.clear()
      return
    }
    ensureInit()
    chart?.setOption(resolveOption(), { notMerge: true, lazyUpdate: true })
  },
  { deep: true },
)

watch(themeRef, () => {
  if (chart && !props.empty) chart.setOption(resolveOption(), { notMerge: true, lazyUpdate: true })
})

watch(
  () => props.empty,
  (isEmpty) => {
    if (isEmpty) {
      disposeChart()
      return
    }
    nextTick(ensureInit)
  },
)

onMounted(() => {
  nextTick(() => {
    if (!props.empty) ensureInit()
    if (el.value && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(scheduleResize)
      observer.observe(el.value)
    }
  })
})

onBeforeUnmount(() => {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = null
  disposeChart()
  observer?.disconnect()
  observer = null
})
</script>

<template>
  <figure class="chart-panel">
    <figcaption>{{ ariaLabel || chartId }}</figcaption>

    <div v-if="empty" class="empty-state">
      <p class="empty-state__title">{{ emptyText }}</p>
    </div>

    <template v-else>
      <div
        :id="chartId"
        ref="el"
        class="chart-canvas"
        :style="{ height }"
        role="img"
        :aria-label="ariaLabel || chartId"
        tabindex="0"
      ></div>

      <details v-if="table && table.rows && table.rows.length">
        <summary>查看数据表（{{ table.rows.length }} 行）</summary>
        <table>
          <thead>
            <tr>
              <th v-for="column in table.columns" :key="column.key" scope="col">{{ column.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in table.rows" :key="index">
              <td v-for="column in table.columns" :key="column.key">{{ row[column.key] }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </template>
  </figure>
</template>