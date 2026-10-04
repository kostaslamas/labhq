import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppI18n } from '@/i18n'

const get = vi.fn()
const post = vi.fn()

vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args), POST: (...args: unknown[]) => post(...args) },
}))

import AddAgentForm from './AddAgentForm.vue'

const KINDS = [
  {
    name: 'claude',
    display_name: 'Claude Code (SDK)',
    adapter: 'claude',
    binary: 'claude',
    available: true,
  },
  { name: 'codex', display_name: 'Codex', adapter: 'tmux', binary: 'codex', available: false },
  { name: 'aider', display_name: 'Aider', adapter: 'tmux', binary: 'aider', available: true },
]

function mountForm() {
  return mount(AddAgentForm, {
    props: { projectId: 7, team: [] },
    global: { plugins: [createAppI18n({ locale: 'en' })] },
  })
}

describe('AddAgentForm', () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({ data: KINDS })
    post.mockReset()
  })

  it('lists the kinds the server returns and disables one whose program is missing', async () => {
    const wrapper = mountForm()
    await flushPromises()

    const options = wrapper.findAll('[data-testid="agent-kind"] option')
    expect(options.map((option) => option.attributes('value'))).toEqual([
      'claude',
      'codex',
      'aider',
    ])
    expect(options[1]?.attributes('disabled')).toBeDefined()
    expect(options[1]?.text()).toContain('codex was not found on this machine')
    expect(options[0]?.attributes('disabled')).toBeUndefined()
  })

  it('sends the chosen kind and reports the approval that is waiting', async () => {
    post.mockResolvedValue({ data: { approval_id: 12 } })
    const wrapper = mountForm()
    await flushPromises()

    await wrapper.get('input[name="title"]').setValue('Coder')
    await wrapper.get('input[name="budget"]').setValue('2.50')
    await wrapper.get('[data-testid="agent-kind"]').setValue('aider')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(post).toHaveBeenCalledWith('/api/projects/{project_id}/agents', {
      params: { path: { project_id: 7 } },
      body: {
        role: 'worker',
        title: 'Coder',
        kind: 'aider',
        reports_to: null,
        budget_micros: 2_500_000,
      },
    })
    expect(wrapper.emitted('added')).toEqual([[12]])
  })

  it('explains a refusal in words and keeps the form', async () => {
    post.mockResolvedValue({ error: { error: { code: 'reporting_line', message: 'x' } } })
    const wrapper = mountForm()
    await flushPromises()

    await wrapper.get('input[name="title"]').setValue('Coder')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[data-testid="form-error"]').text()).toBe(
      'That role cannot report to the chosen agent.',
    )
    expect(wrapper.emitted('added')).toBeUndefined()
  })

  it('refuses a budget that is not a plain amount before asking the server', async () => {
    const wrapper = mountForm()
    await flushPromises()

    await wrapper.get('input[name="title"]').setValue('Coder')
    await wrapper.get('input[name="budget"]').setValue('lots')
    await wrapper.get('form').trigger('submit')

    expect(post).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="form-error"]').text()).toContain('plain amount')
  })
})
