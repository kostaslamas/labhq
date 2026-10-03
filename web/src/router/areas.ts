import type { RouteRecordRaw } from 'vue-router'

import type { NavEntry } from './meta'

export interface AreaRoutesModule {
  default: RouteRecordRaw[]
}

export interface NavItem extends NavEntry {
  path: string
}

// Sorted by file path so the route table does not depend on glob order.
export function collectAreaRoutes(modules: Record<string, AreaRoutesModule>): RouteRecordRaw[] {
  return Object.entries(modules)
    .sort(([left], [right]) => left.localeCompare(right))
    .flatMap(([, module]) => module.default)
}

export function navItems(routes: readonly RouteRecordRaw[]): NavItem[] {
  return routes
    .flatMap((route) => (route.meta?.nav ? [{ ...route.meta.nav, path: route.path }] : []))
    .sort((left, right) => left.order - right.order)
}
