import { Sun } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/today',
    name: 'today',
    component: () => import('./TodayPage.vue'),
    meta: { nav: { labelKey: 'today.nav', icon: Sun, order: 10 } },
  },
]

export default routes
