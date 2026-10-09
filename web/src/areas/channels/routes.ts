import type { RouteRecordRaw } from 'vue-router'

// No `nav` entry: the sidebar has four items (plan §8.1). The Call Center sends the link when
// the owner asks for another channel, and the login and alert messages point here.
const routes: RouteRecordRaw[] = [
  {
    path: '/channels',
    name: 'channels',
    component: () => import('./ChannelsPage.vue'),
  },
]

export default routes
