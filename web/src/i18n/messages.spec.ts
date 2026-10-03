import { describe, expect, it } from 'vitest'

import el from './locales/el.json'
import en from './locales/en.json'
import { collectAreaMessages, mergeCatalogs, type MessageTree } from './messages'
import { nextLocale } from './index'

function flatten(tree: MessageTree, prefix = ''): Record<string, string> {
  return Object.fromEntries(
    Object.entries(tree).flatMap(([key, value]) => {
      const path = prefix ? `${prefix}.${key}` : key
      return typeof value === 'string' ? [[path, value]] : Object.entries(flatten(value, path))
    }),
  )
}

describe('shell messages', () => {
  it('define the same keys in el and en', () => {
    expect(Object.keys(flatten(el)).sort()).toEqual(Object.keys(flatten(en)).sort())
  })

  it('translate every shell string, so switching language changes each one', () => {
    const greek = flatten(el)
    const same = Object.entries(flatten(en)).filter(([key, value]) => greek[key] === value)
    expect(same).toEqual([])
  })
})

describe('area messages', () => {
  it('namespace each area under its folder name', () => {
    const catalog = collectAreaMessages({
      '../areas/today/locales/en.json': { default: { nav: 'Today' } },
      '../areas/today/locales/el.json': { default: { nav: 'Σήμερα' } },
    })
    expect(catalog.en).toEqual({ today: { nav: 'Today' } })
    expect(catalog.el).toEqual({ today: { nav: 'Σήμερα' } })
  })

  it('refuse a locale the UI does not support', () => {
    expect(() =>
      collectAreaMessages({ '../areas/today/locales/fr.json': { default: { nav: 'x' } } }),
    ).toThrow(/not an area locale file/)
  })

  it('refuse an area that reuses a shell namespace', () => {
    const shell = { el: { status: {} }, en: { status: {} } }
    expect(() => mergeCatalogs(shell, { el: { status: {} }, en: {} })).toThrow(/status/)
  })
})

describe('nextLocale', () => {
  it('cycles through the supported locales', () => {
    expect(nextLocale('el')).toBe('en')
    expect(nextLocale('en')).toBe('el')
  })
})
