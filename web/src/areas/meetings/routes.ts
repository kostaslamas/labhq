import { Users } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/meetings',
    name: 'meetings',
    component: () => import('./MeetingsPage.vue'),
    meta: { nav: { labelKey: 'meetings.nav', icon: Users, order: 30 } },
  },
  {
    // Not in the sidebar: it is reached from the list.
    path: '/meetings/:id(\\d+)',
    name: 'meeting',
    component: () => import('./MeetingPage.vue'),
    props: (route) => ({ id: Number(route.params.id) }),
  },
]

export default routes
