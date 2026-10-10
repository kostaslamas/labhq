import { Crown } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

// The CEO has a tab of its own: who it is and which folders it looks in belong to the CEO,
// not to any one project.
const routes: RouteRecordRaw[] = [
  {
    path: '/ceo',
    name: 'ceo',
    component: () => import('./CeoPage.vue'),
    meta: { nav: { labelKey: 'ceo.nav', icon: Crown, order: 15 } },
  },
]

export default routes
