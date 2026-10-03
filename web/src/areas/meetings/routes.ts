import { Users } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/meetings',
    name: 'meetings',
    component: () => import('./MeetingsPage.vue'),
    meta: { nav: { labelKey: 'meetings.nav', icon: Users, order: 30 } },
  },
]

export default routes
