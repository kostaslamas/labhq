import { Terminal } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

// A fifth sidebar item, by the owner's decision on #205: sessions are worth a place of their own.
const routes: RouteRecordRaw[] = [
  {
    path: '/sessions',
    name: 'sessions',
    component: () => import('./SessionsPage.vue'),
    meta: { nav: { labelKey: 'sessions.nav', icon: Terminal, order: 25 } },
  },
]

export default routes
