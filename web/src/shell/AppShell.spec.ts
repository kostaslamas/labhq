import { describe, expect, it } from 'vitest'

import { renderApp, settle } from './__fixtures__/render'

function shellStrings(root: HTMLElement): string[] {
  const texts = [...root.querySelectorAll('aside *')]
    .filter((node) => node.children.length === 0 && node.textContent?.trim())
    .filter((node) => !node.hasAttribute('translate'))
    .map((node) => node.textContent?.trim() ?? '')
  const labels = [...root.querySelectorAll('[aria-label]')].map(
    (node) => node.getAttribute('aria-label') ?? '',
  )
  return [...texts, ...labels]
}

describe('app shell', () => {
  it('has one sidebar item per area', async () => {
    const { root } = await renderApp('/today')
    const items = [...root.querySelectorAll('[data-testid="nav-item"]')]
    expect(items.map((item) => item.textContent?.trim())).toEqual([
      'Today',
      'CEO',
      'Projects',
      'Meetings',
      'Approvals',
    ])
  })

  it('changes every shell string when switching between en and el', async () => {
    const { root } = await renderApp('/today', { locale: 'en' })
    const english = shellStrings(root)
    root.querySelector<HTMLButtonElement>('[data-testid="switch-language"]')?.click()
    await settle()
    const greek = shellStrings(root)

    expect(document.documentElement.lang).toBe('el')
    expect(greek).toHaveLength(english.length)
    expect(english.filter((text) => greek.includes(text))).toEqual(['CEO'])
    expect(greek).toContain('Σήμερα')

    root.querySelector<HTMLButtonElement>('[data-testid="switch-language"]')?.click()
    await settle()
    expect(shellStrings(root)).toEqual(english)
  })
})
