// @vitest-environment node
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { checkI18n } from './i18n-check.ts'

const fixture = (name: string) =>
  fileURLToPath(new URL(`./__fixtures__/i18n/${name}`, import.meta.url))

describe('i18n check', () => {
  it('passes when every locale defines every key the source uses', () => {
    const report = checkI18n(fixture('complete'))
    expect(report.errors).toEqual([])
    expect(report.keys).toBe(3)
  })

  it('fails on a key that exists in one locale and not the other', () => {
    expect(checkI18n(fixture('missing-key')).errors).toEqual([
      'demo.body: defined in some locales but missing in el',
    ])
  })

  it('fails on a key the source uses that no locale defines', () => {
    expect(checkI18n(fixture('unknown-key')).errors).toEqual([
      'src/areas/demo/routes.ts:2: uses "demo.subtitle", which no locale defines',
    ])
  })

  it('fails when it finds nothing to check', () => {
    expect(checkI18n(fixture('does-not-exist')).errors).toContain('no source files found')
  })

  it('passes on the real web app', () => {
    const report = checkI18n(fileURLToPath(new URL('..', import.meta.url)))
    expect(report.errors).toEqual([])
    expect(report.keys).toBeGreaterThan(10)
  })
})
