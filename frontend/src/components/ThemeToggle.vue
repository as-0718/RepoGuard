<script setup>
import { themeRef, toggleTheme } from '../api/theme.js'
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :title="themeRef === 'dark' ? '切换到浅色' : '切换到深色'"
    @click="toggleTheme"
  >
    <svg v-if="themeRef === 'dark'" width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
    </svg>
    <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
    </svg>
    <span>{{ themeRef === 'dark' ? '切浅色' : '切深色' }}</span>
  </button>
</template>
