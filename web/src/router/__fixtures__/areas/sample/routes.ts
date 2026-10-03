import { FlaskConical } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/sample',
    component: () => import('./SamplePage.vue'),
    meta: { nav: { labelKey: 'sample.nav', icon: FlaskConical, order: 50 } },
  },
  {
    path: '/sample/phone',
    component: () => import('./SamplePage.vue'),
    meta: { layout: 'bare', public: true },
  },
]

export default routes
