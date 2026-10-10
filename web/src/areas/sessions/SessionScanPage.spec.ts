import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { createAppI18n } from '@/i18n'

import type { Scope } from './scope'
import SessionScanPage from './SessionScanPage.vue'

const browser = vi.hoisted(() => ({
  browserSupportsWebAuthn: vi.fn(() => true),
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}))
vi.mock('@simplewebauthn/browser', () => browser)

const assertion = { id: 'cred', rawId: 'cred', type: 'public-key', response: {} }

const empty: Scope = { roots: [], exclude: [], machine_wide: true, suggestion: '/home/o/code' }
const one: Scope = {
  roots: [{ path: '/home/o/code', source: 'stored', removable: true }],
  exclude: ['/home/o/code/old'],
  machine_wide: false,
  suggestion: null,
}

async function render(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer({
    'GET /api/session-scan': () => ({ body: empty }),
    'POST /api/auth/step-up/options': () => ({ body: { challenge: 'c' } }),
    ...routes,
  })
  setAuthClient(server.client)
  const wrapper = mount(SessionScanPage, { global: { plugins: [createAppI18n({ locale: 'en' })] } })
  await flushPromises()
  return { wrapper, ...server }
}

describe('session scan page', () => {
  beforeEach(() => {
    browser.startAuthentication.mockReset()
    browser.startAuthentication.mockResolvedValue(assertion)
  })

  it('says the scan is machine-wide and pre-fills the suggestion', async () => {
    const { wrapper } = await render()

    expect(wrapper.get('[data-testid="machine-wide"]').text()).toContain('whole machine')
    expect((wrapper.get('[data-testid="root-path"]').element as HTMLInputElement).value).toBe(
      '/home/o/code',
    )
  })

  it('adds a folder with a passkey and lists it', async () => {
    const { wrapper, requests } = await render({
      'POST /api/session-scan/roots': () => ({
        status: 201,
        body: { scope: one, warning: null },
      }),
    })

    await wrapper.get('[data-testid="add-root"]').trigger('submit')
    await flushPromises()

    const post = requests.find((r) => r.method === 'POST' && r.path === '/api/session-scan/roots')
    expect(requests.some((r) => r.path === '/api/auth/step-up/options')).toBe(true)
    expect(post?.body).toMatchObject({ path: '/home/o/code', credential: assertion })
    expect(wrapper.get('[data-testid="root-/home/o/code"]').text()).toContain('/home/o/code')
    expect(wrapper.get('[data-testid="excluded"]').text()).toContain('/home/o/code/old')
  })

  it('removes a folder with a passkey', async () => {
    const { wrapper, requests } = await render({
      'GET /api/session-scan': () => ({ body: one }),
      'DELETE /api/session-scan/roots': () => ({ body: empty }),
    })

    await wrapper.get('[data-testid="root-/home/o/code"] button').trigger('click')
    await flushPromises()

    const sent = requests.find((r) => r.method === 'DELETE')
    expect(sent?.body).toMatchObject({ path: '/home/o/code', credential: assertion })
    expect(wrapper.find('[data-testid="machine-wide"]').exists()).toBe(true)
  })

  it('sends nothing when the passkey prompt is dismissed', async () => {
    browser.startAuthentication.mockRejectedValue(
      Object.assign(new Error('dismissed'), { name: 'NotAllowedError' }),
    )
    const { wrapper, requests } = await render()

    await wrapper.get('[data-testid="add-root"]').trigger('submit')
    await flushPromises()

    expect(requests.some((r) => r.method === 'POST' && r.path.endsWith('/roots'))).toBe(false)
    expect(wrapper.find('[data-testid="sessions-failure"]').exists()).toBe(true)
  })

  it('shows the server reason when a folder is refused', async () => {
    const { wrapper } = await render({
      'POST /api/session-scan/roots': () => ({
        status: 422,
        body: { error: { code: 'root_invalid', message: "'/' is too broad", details: null } },
      }),
    })

    await wrapper.get('[data-testid="add-root"]').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[data-testid="sessions-failure"]').text()).toContain('too broad')
  })
})
