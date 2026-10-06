import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { components } from '@/api'
import { createAppI18n } from '@/i18n'

type Member = components['schemas']['TeamMember']

const get = vi.fn()
const post = vi.fn()

vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args), POST: (...args: unknown[]) => post(...args) },
}))

import TeamNode from '../projects/TeamNode.vue'
import ControlKeys from './ControlKeys.vue'

function mountKeys(locale: 'en' | 'el' = 'en') {
  return mount(ControlKeys, {
    props: { agentId: 7 },
    global: { plugins: [createAppI18n({ locale })] },
  })
}

function listing(keys: string[], live = true) {
  get.mockImplementation((path: string) =>
    Promise.resolve(
      path.endsWith('/keys') ? { data: { keys, live } } : { data: { screen: 'mode: plan' } },
    ),
  )
}

describe('ControlKeys', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
  })

  it('shows one button for each key the agent accepts', async () => {
    listing(['escape', 'shift_tab', 'ctrl_c'])
    const wrapper = mountKeys()
    await flushPromises()

    expect(wrapper.get('[data-testid="control-key-escape"]').text()).toBe('Esc (stop)')
    expect(wrapper.get('[data-testid="control-key-shift_tab"]').text()).toBe('Shift+Tab (mode)')
    expect(wrapper.find('[data-testid="control-key-ctrl_c"]').exists()).toBe(true)
  })

  it('names the keys in Greek', async () => {
    listing(['escape'])
    const wrapper = mountKeys('el')
    await flushPromises()

    expect(wrapper.get('[data-testid="control-key-escape"]').text()).toBe('Esc (διακοπή)')
  })

  it('shows nothing for an agent without a live tmux pane', async () => {
    listing([], false)
    const wrapper = mountKeys()
    await flushPromises()

    expect(wrapper.find('[data-testid="control-keys"]').exists()).toBe(false)
  })

  it('sends the named key and shows the screen it returns', async () => {
    listing(['escape', 'shift_tab'])
    post.mockResolvedValue({ data: { key: 'shift_tab', screen: 'mode: auto-accept' } })
    const wrapper = mountKeys()
    await flushPromises()

    await wrapper.get('[data-testid="control-key-shift_tab"]').trigger('click')
    await flushPromises()

    expect(post).toHaveBeenCalledWith('/api/agents/{agent_id}/keys', {
      params: { path: { agent_id: 7 } },
      body: { key: 'shift_tab' },
    })
    expect(wrapper.get('[data-testid="control-screen"]').text()).toBe('mode: auto-accept')
  })

  it('says why a key was refused', async () => {
    listing(['escape'])
    post.mockResolvedValue({
      error: { error: { code: 'no_pane', message: 'Agent 7 has no live tmux pane.' } },
    })
    const wrapper = mountKeys()
    await flushPromises()

    await wrapper.get('[data-testid="control-key-escape"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="control-failure"]').text()).toBe(
      'Agent 7 has no live tmux pane.',
    )
  })
})

describe('TeamNode', () => {
  const member = (adapter: string): Member => ({
    id: 7,
    title: 'Worker',
    role: 'worker',
    adapter,
    kind: adapter,
    adopted: false,
    reports: [],
    reports_to: null,
    status: 'active' as const,
    budget: { budget_micros: 0, spent_micros: 0, state: 'allow' as const, used_percent: 0 },
  })

  beforeEach(() => {
    get.mockReset()
    listing(['escape'])
  })

  it('offers keys for a tmux agent', async () => {
    const wrapper = mount(TeamNode, {
      props: { member: member('tmux'), open: new Set<number>() },
      global: { plugins: [createAppI18n({ locale: 'en' })] },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="control-key-escape"]').exists()).toBe(true)
  })

  it('never asks about an SDK agent and shows no buttons', async () => {
    const wrapper = mount(TeamNode, {
      props: { member: member('claude'), open: new Set<number>() },
      global: { plugins: [createAppI18n({ locale: 'en' })] },
    })
    await flushPromises()

    expect(get).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="control-keys"]').exists()).toBe(false)
  })
})
