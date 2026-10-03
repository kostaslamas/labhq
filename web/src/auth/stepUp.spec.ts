import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from './__fixtures__/server'
import { setAuthClient } from './client'
import { useStepUp } from './stepUp'

const browser = vi.hoisted(() => ({
  browserSupportsWebAuthn: vi.fn(() => true),
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}))
vi.mock('@simplewebauthn/browser', () => browser)

const options = { challenge: 'c', rpId: 'localhost', userVerification: 'required' }
const assertion = { id: 'cred', rawId: 'cred', type: 'public-key', response: {} }

describe('useStepUp', () => {
  beforeEach(() => {
    browser.browserSupportsWebAuthn.mockReturnValue(true)
    browser.startAuthentication.mockReset()
  })

  it('asks the server for a challenge for the purpose, then returns the assertion', async () => {
    const { client, requests } = fakeServer({
      'POST /api/auth/step-up/options': () => ({ body: options }),
    })
    setAuthClient(client)
    browser.startAuthentication.mockResolvedValue(assertion)
    const stepUp = useStepUp()

    const result = await stepUp.requestAssertion('approval:42')

    expect(result).toEqual(assertion)
    expect(requests[0]?.body).toEqual({ purpose: 'approval:42' })
    expect(requests[0]?.headers.get('X-Labhq-Request')).toBe('1')
    expect(browser.startAuthentication).toHaveBeenCalledWith({ optionsJSON: options })
    expect(stepUp.failure.value).toBeNull()
  })

  it('reports a dismissed prompt as cancelled, not as a server fault', async () => {
    const { client } = fakeServer({
      'POST /api/auth/step-up/options': () => ({ body: options }),
    })
    setAuthClient(client)
    browser.startAuthentication.mockRejectedValue(
      Object.assign(new Error('dismissed'), { name: 'NotAllowedError' }),
    )
    const stepUp = useStepUp()

    expect(await stepUp.requestAssertion('approval:42')).toBeNull()
    expect(stepUp.failure.value).toBe('cancelled')
    expect(stepUp.pending.value).toBe(false)
  })

  it('reports a refused purpose without opening the authenticator', async () => {
    const { client } = fakeServer({
      'POST /api/auth/step-up/options': () => ({
        status: 422,
        body: { error: { code: 'purpose_invalid', message: 'no' } },
      }),
    })
    setAuthClient(client)
    const stepUp = useStepUp()

    expect(await stepUp.requestAssertion('anything')).toBeNull()
    expect(stepUp.failure.value).toBe('rejected')
    expect(browser.startAuthentication).not.toHaveBeenCalled()
  })

  it('says so when the browser has no WebAuthn', async () => {
    browser.browserSupportsWebAuthn.mockReturnValue(false)
    const stepUp = useStepUp()

    expect(await stepUp.requestAssertion('approval:42')).toBeNull()
    expect(stepUp.failure.value).toBe('unsupported')
  })
})
