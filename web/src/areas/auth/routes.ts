import type { RouteRecordRaw } from 'vue-router'

// Login and enrollment are public: they are how a visitor gets a session. The passkeys page
// is for the signed-in owner and is reached from the sidebar, so it has no `nav` entry.
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('./LoginPage.vue'),
    meta: { public: true, layout: 'bare' },
  },
  {
    path: '/enroll',
    name: 'enroll',
    component: () => import('./EnrollPage.vue'),
    meta: { public: true, layout: 'bare' },
  },
  {
    path: '/passkeys',
    name: 'passkeys',
    component: () => import('./PasskeysPage.vue'),
  },
]

export default routes
