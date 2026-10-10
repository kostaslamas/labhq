import type { RouteRecordRaw } from 'vue-router'

// No `nav` entry: the sidebar has four items (plan §8.1). The Call Center sends the link when
// the owner asks to search another folder, and onboarding points here.
const routes: RouteRecordRaw[] = [
  {
    path: '/session-scan',
    name: 'session-scan',
    component: () => import('./SessionScanPage.vue'),
  },
]

export default routes
