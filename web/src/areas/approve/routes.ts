import type { RouteRecordRaw } from 'vue-router'

// The target of the approval notification. It is public to the router because the page signs
// in itself: a visitor sees nothing about the approval until the passkey has passed.
const routes: RouteRecordRaw[] = [
  {
    path: '/approve/:id(\\d+)',
    name: 'approve',
    component: () => import('./ApprovePage.vue'),
    meta: { public: true, layout: 'bare' },
  },
]

export default routes
