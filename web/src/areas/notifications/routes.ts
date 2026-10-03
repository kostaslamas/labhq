import type { RouteRecordRaw } from 'vue-router'

// Reached from the sidebar, so it has no `nav` entry; subscribing needs the signed-in owner.
const routes: RouteRecordRaw[] = [
  {
    path: '/notifications',
    name: 'notifications',
    component: () => import('./NotificationsPage.vue'),
  },
]

export default routes
