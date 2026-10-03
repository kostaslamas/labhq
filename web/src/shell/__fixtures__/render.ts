import { flushPromises } from '@vue/test-utils'
import { vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createLabhqApp, type AppOptions } from '../app'

// Mounts the real app, as main.ts does, on a memory history.
export async function renderApp(path: string, options: AppOptions = {}) {
  const built = createLabhqApp({
    history: createMemoryHistory(),
    locale: 'en',
    auth: false,
    ...options,
  })
  await built.router.push(path)
  await built.router.isReady()
  const root = document.createElement('div')
  document.body.replaceChildren(root)
  built.app.mount(root)
  await vi.dynamicImportSettled()
  await flushPromises()
  return { ...built, root }
}

export async function settle(): Promise<void> {
  await vi.dynamicImportSettled()
  await flushPromises()
}
