import { createRouter, createWebHistory, type Router, type RouterHistory } from 'vue-router'

import { collectAreaRoutes, navItems, type AreaRoutesModule } from './areas'
import './meta'

// A new area is a new folder with a routes.ts; nothing here changes.
export const discoveredAreaRoutes = import.meta.glob<AreaRoutesModule>('../areas/*/routes.ts', {
  eager: true,
})

export interface AppRouterOptions {
  areaModules?: Record<string, AreaRoutesModule>
  history?: RouterHistory
}

export function createAppRouter(options: AppRouterOptions = {}): Router {
  const areaRoutes = collectAreaRoutes(options.areaModules ?? discoveredAreaRoutes)
  const home = navItems(areaRoutes)[0]?.path
  return createRouter({
    history: options.history ?? createWebHistory(import.meta.env.BASE_URL),
    routes: [
      ...(home ? [{ path: '/', redirect: home }] : []),
      ...areaRoutes,
      ...(home ? [{ path: '/:pathMatch(.*)*', redirect: home }] : []),
    ],
  })
}
