import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: 'overview',
    component: () => import('../views/OverviewView.vue'),
  },
  {
    path: '/issues',
    name: 'issues',
    component: () => import('../views/IssuesView.vue'),
  },
  {
    path: '/structure',
    name: 'structure',
    component: () => import('../views/StructureView.vue'),
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('../views/AboutView.vue'),
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', redirect: '/overview' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})