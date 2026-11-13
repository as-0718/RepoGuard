<script setup>
const props = defineProps({
  variant: { type: String, default: 'page' },
  count: { type: Number, default: 1 },
})
</script>

<template>
  <div aria-busy="true" aria-live="polite">
    <div v-for="index in count" :key="index" class="skeleton-block">
      <div class="skeleton" :class="`skeleton--${variant}`"></div>
    </div>
  </div>
</template>