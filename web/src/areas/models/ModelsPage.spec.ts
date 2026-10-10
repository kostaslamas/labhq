import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { createAppI18n } from '@/i18n'

import type { ModelCost, Policy } from './models'
import ModelsPage from './ModelsPage.vue'

const browser = vi.hoisted(() => ({
  browserSupportsWebAuthn: vi.fn(() => true),
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}))
vi.mock('@simplewebauthn/browser', () => browser)

const assertion = { id: 'cred', rawId: 'cred', type: 'public-key', response: {} }

const policy: Policy = {
  efforts: ['low', 'medium', 'high'],
  models: [
    {
      id: 'claude-sonnet-5-5',
      display_name: 'Sonnet 5.5',
      input_micros_per_mtok: 2_000_000,
      output_micros_per_mtok: 10_000_000,
    },
    {
      id: 'claude-haiku-5-5',
      display_name: 'Haiku 5.5',
      input_micros_per_mtok: 100_000,
      output_micros_per_mtok: 500_000,
    },
  ],
  rows: [
    {
      key: 'worker',
      kind: 'role',
      model: 'claude-sonnet-5-5',
      effort: 'medium',
      max_output_tokens: null,
    },
    {
      key: 'summary',
      kind: 'task',
      model: 'claude-haiku-5-5',
      effort: 'low',
      max_output_tokens: 16000,
    },
  ],
}

const cost: ModelCost = {
  model: 'claude-haiku-5-5',
  runs: 4,
  cost_micros: 1_500,
  input_tokens: 10,
  output_tokens: 5,
  reference_micros: 52_000,
  saved_micros: 50_500,
}

async function render(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer({
    'GET /api/models': () => ({ body: policy }),
    'GET /api/models/usage': () => ({ body: [cost] }),
    'POST /api/auth/step-up/options': () => ({ body: { challenge: 'c' } }),
    ...routes,
  })
  setAuthClient(server.client)
  const wrapper = mount(ModelsPage, { global: { plugins: [createAppI18n({ locale: 'en' })] } })
  await flushPromises()
  return { wrapper, ...server }
}

describe('models page', () => {
  beforeEach(() => {
    browser.startAuthentication.mockReset()
    browser.startAuthentication.mockResolvedValue(assertion)
  })

  it('shows the table with prices and the cost by model with what it saved', async () => {
    const { wrapper } = await render()

    expect(wrapper.get('[data-testid="row-summary"]').text()).toContain('$0.1000 in')
    expect((wrapper.get('[data-testid="model-summary"]').element as HTMLSelectElement).value).toBe(
      'claude-haiku-5-5',
    )
    const usage = wrapper.get('[data-testid="usage-claude-haiku-5-5"]').text()
    expect(usage).toContain('$0.0015')
    expect(usage).toContain('saved about $0.0505')
  })

  it('saves an edited row with a passkey', async () => {
    const saved: Policy = { ...policy, rows: [{ ...policy.rows[0]!, effort: 'high' }] }
    const { wrapper, requests } = await render({ 'PUT /api/models': () => ({ body: saved }) })

    await wrapper.get('[data-testid="effort-worker"]').setValue('high')
    await wrapper.get('[data-testid="models-form"]').trigger('submit')
    await flushPromises()

    const put = requests.find((r) => r.method === 'PUT' && r.path === '/api/models')
    expect(requests.some((r) => r.path === '/api/auth/step-up/options')).toBe(true)
    expect(put?.body).toMatchObject({
      rows: { worker: { model: 'claude-sonnet-5-5', effort: 'high' } },
      credential: assertion,
    })
    expect(wrapper.find('[data-testid="models-saved"]').exists()).toBe(true)
  })

  it('sends nothing when the passkey prompt is dismissed', async () => {
    browser.startAuthentication.mockRejectedValue(
      Object.assign(new Error('dismissed'), { name: 'NotAllowedError' }),
    )
    const { wrapper, requests } = await render()

    await wrapper.get('[data-testid="models-form"]').trigger('submit')
    await flushPromises()

    expect(requests.some((r) => r.method === 'PUT')).toBe(false)
    expect(wrapper.find('[data-testid="models-failure"]').exists()).toBe(true)
  })
})
