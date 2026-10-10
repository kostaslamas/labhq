import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { createAppI18n } from '@/i18n'

import type { Scope } from './scan'
import SessionScan from './SessionScan.vue'

const browser = vi.hoisted(() => ({
  browserSupportsWebAuthn: vi.fn(() => true),
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}))
vi.mock('@simplewebauthn/browser', () => browser)
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

const assertion = { id: 'cred', rawId: 'cred', type: 'public-key', response: {} }

const scan = {
  scanned_at: null,
  left_out: 0,
  session_count: 0,
  project_count: 0,
  folders_visited: 0,
  capped: false,
  found: [],
}
const wide: Scope = {
  roots: [],
  exclude: [],
  machine_wide: true,
  suggestion: '/home/o/code',
  scan,
}
const found = {
  path: '/home/o/code/site',
  name: 'site',
  relative: 'site',
  markers: ['git', 'Node'],
  last_commit_at: '2026-10-01T10:00:00Z',
}
const narrow: Scope = {
  roots: [{ path: '/home/o/code', source: 'stored', removable: true }],
  exclude: [],
  machine_wide: false,
  suggestion: null,
  scan: { ...scan, scanned_at: '2026-10-10T08:00:00Z', left_out: 3, found: [found] },
}

async function render(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer({
    'GET /api/inventory/roots': () => ({ body: wide }),
    'POST /api/auth/step-up/options': () => ({ body: { challenge: 'c' } }),
    ...routes,
  })
  setAuthClient(server.client)
  const wrapper = mount(SessionScan, {
    global: {
      plugins: [createAppI18n({ locale: 'en' })],
      stubs: { RepositoryBrowser: true },
    },
  })
  await flushPromises()
  return { wrapper, ...server }
}

describe('session scan panel', () => {
  beforeEach(() => {
    browser.startAuthentication.mockReset()
    browser.startAuthentication.mockResolvedValue(assertion)
  })

  it('says the scan is machine-wide until a folder is set', async () => {
    const { wrapper, requests } = await render()

    expect(wrapper.get('[data-testid="scan-toggle"]').text()).toBe('Looking machine-wide')
    expect(wrapper.find('[data-testid="machine-wide"]').exists()).toBe(true)
    expect(requests.some((r) => r.path === '/api/inventory/scan')).toBe(false)
  })

  it('adds a folder with a passkey, then scans once', async () => {
    const { wrapper, requests } = await render({
      'PUT /api/inventory/roots': () => ({ body: { scope: narrow, warnings: [] } }),
      'POST /api/inventory/scan': () => ({ body: narrow.scan }),
      'GET /api/inventory/roots': (() => {
        let calls = 0
        return () => ({ body: calls++ === 0 ? wide : narrow })
      })(),
    })

    await wrapper.get('[data-testid="root-path"]').setValue('/home/o/code')
    await wrapper.get('[data-testid="add-root"]').trigger('submit')
    await flushPromises()

    const put = requests.find((r) => r.method === 'PUT')
    expect(put?.body).toMatchObject({
      roots: ['/home/o/code'],
      exclude: [],
      credential: assertion,
    })
    expect(requests.filter((r) => r.path === '/api/inventory/scan')).toHaveLength(1)
    expect(wrapper.get('[data-testid="left-out"]').text()).toBe('3 sessions left out')
    expect(wrapper.get('[data-testid="found-site"]').text()).toContain('git, Node')
  })

  it('offers Add project for a found project with its folder', async () => {
    const { wrapper } = await render({
      'GET /api/inventory/roots': () => ({ body: narrow }),
    })

    await wrapper.get('[data-testid="found-add"]').trigger('click')

    expect(wrapper.emitted('add')?.[0]).toEqual([found])
  })

  it('records "Not interested" with a passkey', async () => {
    const { wrapper, requests } = await render({
      'GET /api/inventory/roots': () => ({ body: narrow }),
      'POST /api/inventory/exclusions': () => ({
        status: 201,
        body: { ...narrow, scan: { ...narrow.scan, found: [] } },
      }),
    })

    await wrapper.get('[data-testid="found-skip"]').trigger('click')
    await flushPromises()

    const post = requests.find((r) => r.path === '/api/inventory/exclusions')
    expect(post?.body).toMatchObject({ path: '/home/o/code/site', credential: assertion })
    expect(wrapper.find('[data-testid="found"]').exists()).toBe(false)
  })

  it('sends nothing when the passkey prompt is dismissed', async () => {
    browser.startAuthentication.mockRejectedValue(
      Object.assign(new Error('dismissed'), { name: 'NotAllowedError' }),
    )
    const { wrapper, requests } = await render()

    await wrapper.get('[data-testid="root-path"]').setValue('/home/o/code')
    await wrapper.get('[data-testid="add-root"]').trigger('submit')
    await flushPromises()

    expect(requests.some((r) => r.method === 'PUT')).toBe(false)
    expect(wrapper.find('[data-testid="sessions-failure"]').exists()).toBe(true)
  })

  it('shows the reason when a folder is refused, and says when the walk was capped', async () => {
    const { wrapper } = await render({
      'GET /api/inventory/roots': () => ({
        body: { ...narrow, scan: { ...narrow.scan, capped: true, folders_visited: 20000 } },
      }),
      'PUT /api/inventory/roots': () => ({
        status: 422,
        body: { error: { code: 'root_invalid', message: "'/' is too broad", details: null } },
      }),
    })

    expect(wrapper.get('[data-testid="capped"]').text()).toContain('20000 folders')
    await wrapper.get('[data-testid="root-path"]').setValue('/')
    await wrapper.get('[data-testid="add-root"]').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[data-testid="sessions-failure"]').text()).toContain('too broad')
  })
})
