import type { RouteRecordRaw } from 'vue-router'

// No `nav` entry: the sidebar has four items (plan §8.1). The Call Center points here when
// the owner asks to change a model, and the approval it raises is confirmed with the passkey.
const routes: RouteRecordRaw[] = [
  {
    path: '/models',
    name: 'models',
    component: () => import('./ModelsPage.vue'),
  },
]

export default routes
