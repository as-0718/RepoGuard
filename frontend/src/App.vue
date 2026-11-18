<script setup>
import { ref, computed, onErrorCaptured } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'

const route = useRoute()
const fatalError = ref(null)
const standalone = computed(() => route.meta?.standalone === true)

onErrorCaptured((error) => {
  fatalError.value = error?.message || '未知错误'
  return false
})
</script>

<template>
  <AppShell v-if="!standalone">
    <div v-if="fatalError" class="card fatal-panel" role="alert">
      <h1 class="page-title">页面渲染失败</h1>
      <p class="page-subtitle">{{ fatalError }}</p>
      <button type="button" class="btn" @click="fatalError = null">尝试恢复</button>
    </div>
    <router-view v-else v-slot="{ Component }">
      <component :is="Component" />
    </router-view>
  </AppShell>
  <router-view v-else />
</template>
