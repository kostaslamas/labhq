import { afterEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { renderApp } from '@/shell/__fixtures__/render'

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/605'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('notifications page', () => {
  it('tells an iPhone tab to add the app to the Home Screen instead of failing quietly', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(IPHONE)
    vi.stubGlobal('isSecureContext', true)
    setAuthClient(
      fakeServer({ 'GET /api/push/status': () => ({ body: { public_key: 'B', active: true } }) })
        .client,
    )

    const { root } = await renderApp('/notifications')

    expect(root.querySelector('[data-testid="needs-install"]')?.textContent).toContain(
      'Add labhq to your Home Screen first',
    )
    expect(root.querySelector('[data-testid="enable-notifications"]')).toBeNull()
  })

  it('warns when Web Push is not the active notifier', async () => {
    vi.stubGlobal('isSecureContext', true)
    setAuthClient(
      fakeServer({ 'GET /api/push/status': () => ({ body: { public_key: 'B', active: false } }) })
        .client,
    )

    const { root } = await renderApp('/notifications')

    expect(root.querySelector('[data-testid="push-inactive"]')?.textContent).toContain(
      'LABHQ_NOTIFY_KIND=webpush',
    )
  })
})
