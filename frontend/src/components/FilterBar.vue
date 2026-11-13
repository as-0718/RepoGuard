<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({ riskLevel: 'all', sourceModule: 'all', keyword: '' }),
  },
  moduleOptions: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  maxKeywordLength: { type: Number, default: 64 },
})

const emit = defineEmits(['update:modelValue', 'submit', 'reset'])

const value = computed(() => ({
  riskLevel: props.modelValue?.riskLevel || 'all',
  sourceModule: props.modelValue?.sourceModule || 'all',
  keyword: props.modelValue?.keyword || '',
}))

function patch(partial) {
  emit('update:modelValue', { ...value.value, ...partial })
}

function onKeyword(event) {
  patch({ keyword: event.target.value.slice(0, props.maxKeywordLength) })
}

function submit() {
  emit('submit', { ...value.value })
}

function reset() {
  emit('reset')
}
</script>

<template>
  <form class="filter-bar" role="search" @submit.prevent="submit">
    <div class="filter-field">
      <label for="filter-risk">风险等级</label>
      <select
        id="filter-risk"
        :value="value.riskLevel"
        :disabled="disabled"
        @change="patch({ riskLevel: $event.target.value })"
      >
        <option value="all">全部</option>
        <option value="high">高风险</option>
        <option value="suggestion">建议</option>
      </select>
    </div>

    <div class="filter-field">
      <label for="filter-module">来源模块</label>
      <select
        id="filter-module"
        :value="value.sourceModule"
        :disabled="disabled"
        @change="patch({ sourceModule: $event.target.value })"
      >
        <option value="all">全部</option>
        <option v-for="module in moduleOptions" :key="module" :value="module">{{ module }}</option>
      </select>
    </div>

    <div class="filter-field filter-field--grow">
      <label for="filter-keyword">关键词</label>
      <input
        id="filter-keyword"
        type="search"
        :value="value.keyword"
        :maxlength="maxKeywordLength"
        :disabled="disabled"
        placeholder="文件路径 / 规则 / 描述"
        @input="onKeyword"
        @keydown.enter.prevent="submit"
      />
    </div>

    <div class="filter-actions">
      <button type="submit" class="btn btn--primary" :disabled="disabled">查询</button>
      <button type="button" class="btn" :disabled="disabled" @click="reset">重置</button>
    </div>
  </form>
</template>