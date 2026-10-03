import { createPinia } from 'pinia'
import { createApp, type App } from 'vue'

import AppRoot from '@/App.vue'
import { createAppI18n, type AppI18nOptions } from '@/i18n'
import { createAppRouter, type AppRouterOptions } from '@/router'
import { appI18nKey } from './useAppI18n'

export type AppOptions = AppRouterOptions & AppI18nOptions

// Tests build the same app with fixture areas; main.ts builds it with the discovered ones.
export function createLabhqApp(options: AppOptions = {}) {
  const router = createAppRouter(options)
  const i18n = createAppI18n(options)
  const app: App = createApp(AppRoot)
  app.use(createPinia()).use(router).use(i18n).provide(appI18nKey, i18n)
  return { app, router, i18n }
}
