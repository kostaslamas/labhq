import { describe, expect, it } from 'vitest'

import { discoveredAreaMessages } from '@/i18n'
import type { LocaleModule } from '@/i18n/messages'
import { renderApp, settle } from '@/shell/__fixtures__/render'

import { collectAreaRoutes, navItems, type AreaRoutesModule } from './areas'
import { discoveredAreaRoutes } from './index'

// The fixture area sits outside src/areas, so it reaches the app only as these modules: the
// same shape the router and the i18n loader discover with import.meta.glob.
const fixtureRoutes = import.meta.glob<AreaRoutesModule>('./__fixtures__/areas/*/routes.ts', {
  eager: true,
})
const fixtureMessages = import.meta.glob<LocaleModule>('./__fixtures__/areas/*/locales/*.json', {
  eager: true,
})
const withFixture = {
  areaModules: { ...discoveredAreaRoutes, ...fixtureRoutes },
  areaMessages: { ...discoveredAreaMessages, ...fixtureMessages },
}

describe('area discovery', () => {
  it('discovers the areas in sidebar order', () => {
    const items = navItems(collectAreaRoutes(discoveredAreaRoutes))
    expect(items.map((item) => item.path)).toEqual([
      '/today',
      '/projects',
      '/sessions',
      '/meetings',
      '/approvals',
    ])
  })

  it('redirects the root and unknown paths to the first area', async () => {
    const { router } = await renderApp('/')
    expect(router.currentRoute.value.path).toBe('/today')
    await router.push('/nowhere')
    expect(router.currentRoute.value.path).toBe('/today')
  })

  it('adds a fixture area route and its messages without editing the router or loader', async () => {
    const { root, i18n } = await renderApp('/sample', withFixture)
    expect(root.querySelector('[data-testid="sample-heading"]')?.textContent).toBe('Sample area')
    const labels = [...root.querySelectorAll('[data-testid="nav-item"]')].map((n) => n.textContent)
    expect(labels).toContain('Sample')
    expect(i18n.global.t('sample.heading', {}, { locale: 'el' })).toBe('Περιοχή δείγματος')
  })

  it('renders a route with layout bare without the sidebar', async () => {
    const { root, router } = await renderApp('/sample/phone', withFixture)
    expect(router.currentRoute.value.meta.public).toBe(true)
    expect(root.querySelector('[data-testid="sample-heading"]')).not.toBeNull()
    expect(root.querySelector('nav')).toBeNull()
    await router.push('/sample')
    await settle()
    expect(root.querySelector('nav')).not.toBeNull()
  })
})
