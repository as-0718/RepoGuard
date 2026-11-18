import { createRouter, createWebHistory } from 'vue-router'
import { getStoredRepo } from '@api/repoStore.js'

const routes = [
  { path: '/', redirect: '/welcome' },
  {
    path: '/welcome',
    name: 'welcome',
    meta: { standalone: true },
    component: () => import('../views/WelcomeView.vue'),
  },
  {
    path: '/select',
    name: 'select',
    meta: { standalone: true },
    component: () => import('../views/SelectView.vue'),
  },
  {
    path: '/overview',
    name: 'overview',
    meta: { requiresRepo: true },
    component: () => import('../views/OverviewView.vue'),
  },
  {
    path: '/issues',
    name: 'issues',
    meta: { requiresRepo: true },
    component: () => import('../views/IssuesView.vue'),
  },
  {
    path: '/structure',
    name: 'structure',
    meta: { requiresRepo: true },
    component: () => import('../views/StructureView.vue'),
  },
  {
    path: '/history',
    name: 'history',
    meta: { requiresRepo: true },
    component: () => import('../views/HistoryView.vue'),
  },
  {
    path: '/about',
    name: 'about',
    meta: { requiresRepo: true },
    component: () => import('../views/AboutView.vue'),
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', redirect: '/welcome' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  if (to.meta.requiresRepo) {
    const repo = typeof to.query.repo === 'string' && to.query.repo ? to.query.repo : getStoredRepo()
    if (!repo) {
      return { path: '/select', query: { redirect: to.fullPath } }
    }
  }
  return true
})

export default router
