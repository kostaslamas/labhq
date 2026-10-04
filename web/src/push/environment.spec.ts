import { describe, expect, it } from 'vitest'

import { pushAvailability, type PushFacts } from './environment'

const DESKTOP: PushFacts = {
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130',
  platform: 'Linux x86_64',
  maxTouchPoints: 0,
  standalone: false,
  secureContext: true,
  hasServiceWorker: true,
  hasPushManager: true,
  permission: 'default',
}
const IPHONE: PushFacts = {
  ...DESKTOP,
  userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/605',
  platform: 'iPhone',
  maxTouchPoints: 5,
}

describe('pushAvailability', () => {
  it('is available in a desktop browser that has not been asked yet', () => {
    expect(pushAvailability(DESKTOP)).toBe('available')
  })

  it('asks an iPhone tab to add the app to the Home Screen, even though PushManager is hidden', () => {
    expect(pushAvailability({ ...IPHONE, hasPushManager: false })).toBe('needs_install')
  })

  it('treats an iPad that reports a Mac as iOS', () => {
    const ipad = { ...DESKTOP, platform: 'MacIntel', maxTouchPoints: 5 }
    expect(pushAvailability(ipad)).toBe('needs_install')
    expect(pushAvailability({ ...ipad, maxTouchPoints: 0 })).toBe('available')
  })

  it('is available once the app runs from the Home Screen', () => {
    expect(pushAvailability({ ...IPHONE, standalone: true })).toBe('available')
  })

  it('reports blocked notifications as denied', () => {
    expect(pushAvailability({ ...DESKTOP, permission: 'denied' })).toBe('denied')
  })

  it.each([
    ['an insecure page', { secureContext: false }],
    ['no service worker', { hasServiceWorker: false }],
    ['no push manager', { hasPushManager: false }],
    ['no Notification API', { permission: 'unsupported' as const }],
  ])('is unsupported with %s', (_name, change) => {
    expect(pushAvailability({ ...DESKTOP, ...change })).toBe('unsupported')
  })
})
