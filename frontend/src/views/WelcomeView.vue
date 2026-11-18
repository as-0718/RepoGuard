<script setup>
import { useRouter } from 'vue-router'
import { setStoredRepo } from '@api/repoStore.js'
import ThemeToggle from '../components/ThemeToggle.vue'

const router = useRouter()

function startSelect() {
  router.push('/select')
}

function useDemo() {
  setStoredRepo('demo-repo')
  router.push({ path: '/overview', query: { repo: 'demo-repo' } })
}
</script>

<template>
  <div class="welcome-page">
    <ThemeToggle class="theme-toggle--float" />
    <section class="welcome-card card">
      <h1 class="page-title">RepoGuard 代码巡检工具</h1>
      <p class="page-subtitle">
        面向本地代码仓库的只读静态巡检：检查命名与目录、代码规范、链接有效性、敏感信息与大文件，以及 README / 文档结构。
      </p>

      <div class="notice notice--degraded" role="status">
        使用前请阅读以下须知
      </div>

      <ul class="notice-list">
        <li>
          <strong>本地运行，不上传代码：</strong>所有扫描与分析都在你的电脑本机完成，不会把仓库内容发送到任何外部服务器。
        </li>
        <li>
          <strong>只读巡检：</strong>工具不会修改、删除或提交你仓库里的任何文件，仅读取并生成报告。
        </li>
        <li>
          <strong>路径要求：</strong>请填写项目文件夹的绝对路径（文件夹这一层即可）；系统敏感目录（如 Windows、Program Files）不可选。
        </li>
        <li>
          <strong>结果仅供参考：</strong>报告基于规则引擎的静态分析，可能存在误报或漏报，建议结合人工复核。
        </li>
      </ul>

      <div class="welcome-actions">
        <button type="button" class="btn btn--primary" @click="startSelect">开始使用</button>
        <button type="button" class="btn" @click="useDemo">试用示例仓库</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.welcome-page {
  min-height: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
}

.welcome-card {
  width: 100%;
  max-width: 720px;
}

.notice-list {
  margin: 0 0 24px;
  padding-left: 20px;
  display: grid;
  gap: 12px;
  color: var(--color-text);
  font-size: 14px;
  line-height: 1.7;
}

.welcome-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.welcome-actions .btn {
  padding: 8px 18px;
}
</style>
