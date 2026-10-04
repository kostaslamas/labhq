import { MessageCircle } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/ceo',
    name: 'ceo-chat',
    component: () => import('./ChatPage.vue'),
    meta: { nav: { labelKey: 'ceo.nav', icon: MessageCircle, order: 15 } },
  },
]

export default routes
