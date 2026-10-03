import { FolderKanban } from 'lucide-vue-next'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/projects',
    name: 'projects',
    component: () => import('./ProjectsPage.vue'),
    meta: { nav: { labelKey: 'projects.nav', icon: FolderKanban, order: 20 } },
  },
]

export default routes
