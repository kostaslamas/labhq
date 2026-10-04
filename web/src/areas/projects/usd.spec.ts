import { describe, expect, it } from 'vitest'

import { usdToMicros } from './usd'

describe('usdToMicros', () => {
  it.each([
    ['25', 25_000_000],
    ['2.50', 2_500_000],
    ['0.0097', 9_700],
    [' 1.000001 ', 1_000_001],
    ['0', 0],
  ])('reads %s as %d micros', (text, micros) => {
    expect(usdToMicros(text)).toBe(micros)
  })

  it('treats an empty field as no budget', () => {
    expect(usdToMicros('')).toBeNull()
    expect(usdToMicros('  ')).toBeNull()
  })

  it.each(['-1', '1.2345678', '1,5', 'abc', '$5', '1e3', '.5'])('refuses %s', (text) => {
    expect(usdToMicros(text)).toBeUndefined()
  })
})
