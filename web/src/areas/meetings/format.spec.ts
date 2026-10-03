import { describe, expect, it } from 'vitest'

import { avatarHue, formatInstant, initials } from './format'

describe('meetings format', () => {
  it('takes up to two initials, in upper case', () => {
    expect(initials('Backend lead')).toBe('BL')
    expect(initials('worker')).toBe('W')
    expect(initials('  Project  manager  of all ')).toBe('PM')
    expect(initials('')).toBe('')
  })

  it('gives an agent the same hue every time, inside the colour wheel', () => {
    expect(avatarHue(7)).toBe(avatarHue(7))
    for (const id of [1, 2, 99, 12345]) {
      expect(avatarHue(id)).toBeGreaterThanOrEqual(0)
      expect(avatarHue(id)).toBeLessThan(360)
    }
    expect(avatarHue(1)).not.toBe(avatarHue(2))
  })

  it('formats a UTC instant in the viewer zone', () => {
    const text = formatInstant('en-US', '2026-10-02T09:00:00Z', {
      timeZone: 'UTC',
      timeStyle: 'short',
    })
    expect(text).toBe('9:00 AM')
  })
})
