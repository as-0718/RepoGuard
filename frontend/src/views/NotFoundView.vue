<script setup>
import { RouterLink } from 'vue-router'
</script>

<template>
  <section>
    <h1 class="page-title">页面不存在</h1>
    <p class="page-subtitle">你访问的地址不存在或已被移除。</p>
    <RouterLink class="btn btn--primary" to="/overview">返回总览</RouterLink>
  </section>
</template>