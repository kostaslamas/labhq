import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { createAppI18n } from '@/i18n'

import ApprovalActions from './ApprovalActions.vue'
import type { Approval } from './decide'

const browser = vi.hoisted(() => ({
  browserSupportsWebAuthn: vi.fn(() => true),
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}))
vi.mock('@simplewebauthn/browser', () => browser)

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: 7,
    type: 'assign_task',
    risk_class: 'light',
    status: 'pending',
    payload: {},
    project: null,
    task: null,
    requester: null,
    branch: null,
    remote: null,
    created_at: '2026-10-03T09:00:00Z',
    decided_by: null,
    decided_at: null,
    confirmation_kind: null,
    decision_note: null,
    executed_at: null,
    execution: null,
    ...overrides,
  }
}

function render(row: Approval) {
  return mount(ApprovalActions, {
    props: { approval: row },
    global: { plugins: [createAppI18n({ locale: 'en' })] },
  })
}

const decisionPath = 'POST /api/approvals/7/decision'
const stepUpPath = 'POST /api/auth/step-up/options'

describe('ApprovalActions', () => {
  beforeEach(() => {
    browser.browserSupportsWebAuthn.mockReturnValue(true)
    browser.startAuthentication.mockReset()
  })

  it('approves a light approval with one request and no passkey prompt', async () => {
    const decided = approval({ status: 'approved', confirmation_kind: 'tap' })
    const { client, requests } = fakeServer({ [decisionPath]: () => ({ body: decided }) })
    setAuthClient(client)
    const wrapper = render(approval())

    await wrapper.get('[data-testid="approve"]').trigger('click')
    await flushPromises()

    expect(requests).toHaveLength(1)
    expect(requests[0]?.body).toEqual({ decision: 'approve', credential: null })
    expect(requests[0]?.headers.get('Idempotency-Key')).toBeTruthy()
    expect(browser.startAuthentication).not.toHaveBeenCalled()
    expect(wrapper.emitted('decided')?.[0]).toEqual([decided])
  })

  it('sends the passkey assertion with a heavy approval', async () => {
    const assertion = { id: 'cred', rawId: 'cred', type: 'public-key', response: {} }
    browser.startAuthentication.mockResolvedValue(assertion)
    const { client, requests } = fakeServer({
      [stepUpPath]: () => ({ body: { challenge: 'c' } }),
      [decisionPath]: () => ({ body: approval({ status: 'executed' }) }),
    })
    setAuthClient(client)
    const wrapper = render(approval({ risk_class: 'heavy', type: 'push' }))

    await wrapper.get('[data-testid="approve"]').trigger('click')
    await flushPromises()

    expect(requests[0]?.body).toEqual({ purpose: 'approval:7' })
    expect(requests[1]?.body).toEqual({ decision: 'approve', credential: assertion })
  })

  it('leaves a heavy approval pending, with a plain message, when the prompt is dismissed', async () => {
    browser.startAuthentication.mockRejectedValue(
      Object.assign(new Error('dismissed'), { name: 'NotAllowedError' }),
    )
    const { client, requests } = fakeServer({ [stepUpPath]: () => ({ body: { challenge: 'c' } }) })
    setAuthClient(client)
    const wrapper = render(approval({ risk_class: 'heavy' }))

    await wrapper.get('[data-testid="approve"]').trigger('click')
    await flushPromises()

    expect(requests.map((request) => request.path)).toEqual(['/api/auth/step-up/options'])
    expect(wrapper.get('[data-testid="decision-error"]').text()).toContain('still pending')
    expect(wrapper.emitted('decided')).toBeUndefined()
  })

  it('shows the server refusal and keeps the approval pending', async () => {
    browser.startAuthentication.mockResolvedValue({ id: 'cred' })
    const { client } = fakeServer({
      [stepUpPath]: () => ({ body: { challenge: 'c' } }),
      [decisionPath]: () => ({
        status: 403,
        body: { error: { code: 'challenge_invalid', message: 'no' } },
      }),
    })
    setAuthClient(client)
    const wrapper = render(approval({ risk_class: 'heavy' }))

    await wrapper.get('[data-testid="approve"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="decision-error"]').text()).toContain('did not accept')
    expect(wrapper.emitted('decided')).toBeUndefined()
  })

  it('offers no action on an approval that is no longer pending', () => {
    const wrapper = render(approval({ status: 'approved', decided_by: 'gate:ci' }))
    expect(wrapper.find('[data-testid="approve"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="reject"]').exists()).toBe(false)
  })
})
