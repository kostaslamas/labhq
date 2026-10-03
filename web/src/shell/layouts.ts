import type { Component } from 'vue'

import type { LayoutName } from '@/router/meta'

import AppShell from './AppShell.vue'
import BareLayout from './BareLayout.vue'

export const layouts: Record<LayoutName, Component> = {
  shell: AppShell,
  bare: BareLayout,
}
