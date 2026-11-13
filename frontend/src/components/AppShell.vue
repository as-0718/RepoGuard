<script setup>
import { computed, onMounted, provide, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { listRepos } from '@api/dashboard.js'

const route = useRoute()
const router = useRouter()

const repos = ref([])
const defaultRepo = ref('')
const reposError = ref('')
const reposLoading = ref(true)
const refreshTick = ref(0)
const requesting = ref(false)
const snapshotMeta = ref(null)

const repoId = computed(() => {
  const fromQuery = typeof route.query.repo === 'string' ? route.query.repo : ''
  return fromQuery || defaultRepo.value
})

const meta = computed(() => snapshotMeta.value || {})
const hasMeta = computed(() => Boolean(snapshotMeta.value))
const cachedText = computed(() => (meta.value.cached ? '是' : '否'))
const cacheAgeText = computed(() =>
  typeof meta.value.cache_age_seconds === 'number' ? `${meta.value.cache_age_seconds} 秒` : '—',
)

function setRequesting(value) {
  requesting.value = Boolean(value)
}

function setSnapshotMeta(next) {
  snapshotMeta.value = next || null
}

function setRepo(nextRepo) {
  router.replace({
    query: {
      ...route.query,
      repo: nextRepo,
      page: undefined,
      refresh: undefined,
      _r: undefined,
    },
  })
}

function requestRefresh() {
  refreshTick.value += 1
  router.replace({ query: { ...route.query, refresh: '1', _r: String(Date.now()) } })
}

provide('dashboardContext', {
  repoId,
  refreshTick,
  requesting,
  requestRefresh,
  setRepo,
  snapshotMeta,
  setSnapshotMeta,
  setRequesting,
})

async function loadRepos() {
  reposLoading.value = true
  reposError.value = ''
  try {
    const payload = await listRepos()
    repos.value = Array.isArray(payload?.repos) ? payload.repos : []
    defaultRepo.value = typeof payload?.default_repo === 'string' ? payload.default_repo : ''
  } catch (error) {
    reposError.value = error?.message || '无法获取仓库列表'
  } finally {
    reposLoading.value = false
  }
}

watch([repos, defaultRepo], () => {
  if (!repos.value.length || !defaultRepo.value) return
  if (typeof route.query.repo === 'string' && route.query.repo) return
  router.replace({ query: { ...route.query, repo: defaultRepo.value } })
})

onMounted(loadRepos)
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="header-inner">
        <RouterLink to="/overview" class="brand">
          <span class="brand-mark" aria-hidden="true"></span>
          <span>RepoGuard 只读看板</span>
        </RouterLink>

        <nav class="app-nav" aria-label="主导航">
          <RouterLink to="/overview" aria-current-value="page">总览</RouterLink>
          <RouterLink to="/issues" aria-current-value="page">问题明细</RouterLink>
          <RouterLink to="/structure" aria-current-value="page">结构/README</RouterLink>
          <RouterLink to="/about" aria-current-value="page">关于/健康</RouterLink>
        </nav>

        <div class="header-tools">
          <label for="repo-select">仓库</label>
          <select
            id="repo-select"
            :value="repoId"
            :disabled="reposLoading || !repos.length"
            @change="setRepo($event.target.value)"
          >
            <option v-if="!repos.length" value="">（暂无可用仓库）</option>
            <option v-for="repo in repos" :key="repo.id" :value="repo.id">
              {{ repo.label || repo.id }}
            </option>
          </select>

          <button type="button" :disabled="requesting || !repoId" @click="requestRefresh">
            刷新
          </button>
        </div>
      </div>

      <div class="shell-meta">
        <template v-if="hasMeta">
          <span>扫描时间 <strong>{{ meta.scanned_at || '—' }}</strong></span>
          <span>缓存命中 <strong>{{ cachedText }}</strong></span>
          <span>缓存年龄 <strong>{{ cacheAgeText }}</strong></span>
          <span>刷新节流 <strong>{{ meta.refresh_throttled ? '是' : '否' }}</strong></span>
        </template>
        <span v-else>尚无快照信息</span>
        <span v-if="reposError" class="tone-tag tone-tag--high">{{ reposError }}</span>
      </div>
    </header>

    <main class="app-main">
      <slot />
    </main>
  </div>
</template>