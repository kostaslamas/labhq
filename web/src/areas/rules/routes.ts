import type { RouteRecordRaw } from 'vue-router'

// No `nav` entry: the sidebar has four items (plan §8.1). The page is reached from the infra
// project and from an incident, and lives under the project's path.
const routes: RouteRecordRaw[] = [
  {
    path: '/projects/infra/rules',
    name: 'rules',
    component: () => import('./RulesPage.vue'),
  },
]

export default routes
