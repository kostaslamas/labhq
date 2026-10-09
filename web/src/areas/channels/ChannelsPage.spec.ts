import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { createAppI18n } from '@/i18n'

import type { Channel, ChannelKind } from './channels'
import ChannelsPage from './ChannelsPage.vue'

const browser = vi.hoisted(() => ({
  browserSupportsWebAuthn: vi.fn(() => true),
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}))
vi.mock('@simplewebauthn/browser', () => browser)

const assertion = { id: 'cred', rawId: 'cred', type: 'public-key', response: {} }
const stepUpPath = 'POST /api/auth/step-up/options'

const kinds: ChannelKind[] = [
  {
    kind: 'telegram',
    label: 'Telegram',
    available: true,
    fields: [
      { name: 'chat_id', label: 'the chat id', secret: false, default: null },
      { name: 'token', label: 'the bot token', secret: true, default: null },
    ],
  },
  { kind: 'discord', label: 'Discord', available: false, fields: [] },
]

function channel(overrides: Partial<Channel> = {}): Channel {
  return {
    id: 3,
    name: 'phone',
    kind: 'telegram',
    enabled: true,
    last_test_ok: true,
    last_test_error: null,
    last_tested_at: '2026-10-09T09:00:00Z',
    ...overrides,
  }
}

async function render(routes: Parameters<typeof fakeServer>[0]) {
  const server = fakeServer({
    'GET /api/channels': () => ({ body: [channel()] }),
    'GET /api/channels/kinds': () => ({ body: kinds }),
    [stepUpPath]: () => ({ body: { challenge: 'c' } }),
    ...routes,
  })
  setAuthClient(server.client)
  const wrapper = mount(ChannelsPage, { global: { plugins: [createAppI18n({ locale: 'en' })] } })
  await flushPromises()
  return { wrapper, ...server }
}

describe('channels page', () => {
  beforeEach(() => {
    browser.startAuthentication.mockReset()
    browser.startAuthentication.mockResolvedValue(assertion)
  })

  it('lists the channels with their last test, and a chat service that is not set up is disabled', async () => {
    const { wrapper } = await render({})

    expect(wrapper.get('[data-testid="channel-3"]').text()).toContain('phone')
    expect(wrapper.get('[data-testid="result-3"]').attributes('data-ok')).toBe('true')
    const discord = wrapper.findAll('option').find((o) => o.text().includes('Discord'))
    expect(discord?.attributes('disabled')).toBeDefined()
  })

  it('adds a channel with a passkey, hides the token field and shows the new channel', async () => {
    const added = channel({ id: 4, name: 'second' })
    const { wrapper, requests } = await render({
      'POST /api/channels': () => ({ status: 201, body: { channel: added, error: null } }),
    })
    await wrapper.get('[data-testid="kind"]').setValue('telegram')
    await wrapper.get('[data-testid="name"]').setValue('second')
    await wrapper.get('[data-testid="field-chat_id"]').setValue('42')
    await wrapper.get('[data-testid="field-token"]').setValue('123:SECRET')

    expect(wrapper.get('[data-testid="field-token"]').attributes('type')).toBe('password')
    await wrapper.get('[data-testid="channel-form"]').trigger('submit')
    await flushPromises()

    const post = requests.find((r) => r.method === 'POST' && r.path === '/api/channels')
    expect(requests.some((r) => r.path === '/api/auth/step-up/options')).toBe(true)
    expect(post?.body).toEqual({
      kind: 'telegram',
      name: 'second',
      values: { chat_id: '42', token: '123:SECRET' },
      credential: assertion,
    })
    expect(wrapper.find('[data-testid="channel-4"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('SECRET')
  })

  it('changes nothing when the passkey prompt is dismissed', async () => {
    browser.startAuthentication.mockRejectedValue(
      Object.assign(new Error('dismissed'), { name: 'NotAllowedError' }),
    )
    const { wrapper, requests } = await render({})

    await wrapper.get('[data-testid="remove-3"]').trigger('click')
    await flushPromises()

    expect(requests.some((r) => r.method === 'DELETE')).toBe(false)
    expect(wrapper.find('[data-testid="channel-3"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="channels-failure"]').exists()).toBe(true)
  })

  it('removes a channel after the passkey and sends a test without one', async () => {
    const { wrapper, requests } = await render({
      // The fake server always sends a JSON body, which a 204 cannot carry; any 2xx is a removal.
      'DELETE /api/channels/3': () => ({ status: 200 }),
      'POST /api/channels/3/test': () => ({
        body: {
          channel: channel({ last_test_ok: false, last_test_error: 'HTTPStatusError' }),
          error: 'HTTPStatusError',
        },
      }),
    })

    await wrapper.get('[data-testid="test-3"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="result-3"]').text()).toContain('HTTPStatusError')
    expect(requests.filter((r) => r.path === '/api/auth/step-up/options')).toHaveLength(0)

    await wrapper.get('[data-testid="remove-3"]').trigger('click')
    await flushPromises()
    const remove = requests.find((r) => r.method === 'DELETE')
    expect(remove?.body).toEqual({ credential: assertion })
    expect(wrapper.find('[data-testid="channel-3"]').exists()).toBe(false)
  })
})
