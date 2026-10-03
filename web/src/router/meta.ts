import type { Component } from 'vue'

export const layoutNames = ['shell', 'bare'] as const
export type LayoutName = (typeof layoutNames)[number]

// A route that declares `nav` appears in the sidebar; the shell never lists areas itself.
export interface NavEntry {
  labelKey: string
  icon: Component
  order: number
}

declare module 'vue-router' {
  interface RouteMeta {
    // `bare` drops the sidebar, for the phone approval page.
    layout?: LayoutName
    // Read by the authentication guard, which a later issue adds.
    public?: boolean
    nav?: NavEntry
  }
}
