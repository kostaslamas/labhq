// @vitest-environment node
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { checkDist } from './dist-check.ts'

const fixture = (name: string) =>
  fileURLToPath(new URL(`./__fixtures__/builds/${name}`, import.meta.url))

describe('dist check', () => {
  it('passes a build whose fonts and styles are bundled', () => {
    expect(checkDist(fixture('bundled')).errors).toEqual([])
  })

  it('fails a build that loads fonts from a CDN', () => {
    expect(checkDist(fixture('cdn-font')).errors).toEqual([
      'assets/index.css: references external https://fonts.gstatic.com/plex.woff2',
      'assets/index.css: references external https://fonts.googleapis.com/css2?family=Oxanium',
      'no font files in the build: fonts must be bundled, not linked',
    ])
  })

  it('fails when there is no build to check', () => {
    expect(checkDist(fixture('missing')).errors[0]).toMatch(/no build output/)
  })
})
