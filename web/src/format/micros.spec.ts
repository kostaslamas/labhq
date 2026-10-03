import { describe, expect, it } from 'vitest'

import { formatMicros } from './micros'
import source from './micros.ts?raw'

describe('formatMicros', () => {
  it.each([
    [9700, '$0.0097'],
    [0, '$0.00'],
    [1, '$0.000001'],
    [10_000, '$0.01'],
    [1_500_000, '$1.50'],
    [12_345_678, '$12.345678'],
    [1_234_567_000_000, '$1,234,567.00'],
    [-250_000, '-$0.25'],
  ])('formats %d micros as %s', (micros, expected) => {
    expect(formatMicros(micros)).toBe(expected)
  })

  it('stays exact where float division would round', () => {
    // As a float, 9007199254740991 / 1e6 prints 9007199254.740992.
    expect(formatMicros(Number.MAX_SAFE_INTEGER)).toBe('$9,007,199,254.740991')
    expect(formatMicros(123_456_789_012_345_678n)).toBe('$123,456,789,012.345678')
  })

  it('contains no floating-point formatting or division', () => {
    const code = source.replace(/\/\/.*$/gm, '')
    expect(code).not.toMatch(/toFixed|toPrecision|parseFloat|Math\.|Intl\.NumberFormat/)
    // The one division is bigint by bigint.
    expect(code.match(/\s\/\s\S+/g)).toEqual([' / MICROS_PER_USD'])
    expect(code).toContain('const MICROS_PER_USD = 1_000_000n')
  })

  it.each([0.5, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 53])('refuses %d', (micros) => {
    expect(() => formatMicros(micros)).toThrow(RangeError)
  })
})
