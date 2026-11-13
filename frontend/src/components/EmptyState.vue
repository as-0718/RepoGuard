<script setup>
const props = defineProps({
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  icon: { type: String, default: 'empty' },
})
</script>

<template>
  <div class="empty-state" role="status" :data-icon="icon">
    <p class="empty-state__title">{{ title }}</p>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
  </div>
</template>