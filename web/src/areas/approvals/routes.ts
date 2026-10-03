import { ShieldCheck } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/approvals',
    name: 'approvals',
    component: () => import('./ApprovalsPage.vue'),
    meta: { nav: { labelKey: 'approvals.nav', icon: ShieldCheck, order: 40 } },
  },
]

export default routes
