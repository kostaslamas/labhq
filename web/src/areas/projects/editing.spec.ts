import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { components } from '@/api'
import { createAppI18n } from '@/i18n'

const get = vi.fn()
const patch = vi.fn()
vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args), PATCH: (...args: unknown[]) => patch(...args) },
}))

import AddProjectForm from './AddProjectForm.vue'
import EditAgentForm from './EditAgentForm.vue'

type Member = components['schemas']['TeamMember']
const member: Member = {
  id: 4,
  title: 'Coder',
  role: 'worker',
  adapter: 'tmux',
  kind: 'codex',
  reports_to: null,
  adopted: false,
  status: 'active',
  reports: [],
  budget: { budget_micros: 2_500_000, spent_micros: 0, state: 'allow', used_percent: 0 },
}
const plugins = [createAppI18n({ locale: 'en' })]

describe('project folder suggestions and existing agent edits', () => {
  beforeEach(() => {
    get.mockReset()
    patch.mockReset()
  })

  it('fills the path from an exact project name and offers partial matches', async () => {
    get.mockResolvedValue({ data: [{ name: 'labhq', path: '/srv/work/labhq' }] })
    const wrapper = mount(AddProjectForm, { global: { plugins } })
    await wrapper.get('input[name="name"]').setValue('labhq')
    await new Promise((resolve) => setTimeout(resolve, 300))
    await flushPromises()
    expect((wrapper.get('input[name="repo_path"]').element as HTMLInputElement).value).toBe(
      '/srv/work/labhq',
    )
    expect(wrapper.get('[data-testid="path-suggestions"]').text()).toContain('/srv/work/labhq')
  })

  it('saves changes to the same agent id', async () => {
    get.mockResolvedValue({
      data: [
        { name: 'codex', display_name: 'Codex', adapter: 'tmux', binary: 'codex', available: true },
        { name: 'aider', display_name: 'Aider', adapter: 'tmux', binary: 'aider', available: true },
      ],
    })
    patch.mockResolvedValue({ data: { id: 4 } })
    const wrapper = mount(EditAgentForm, {
      props: { projectId: 9, member, team: [member] },
      global: { plugins },
    })
    await flushPromises()
    await wrapper.get('input[name="title"]').setValue('Reviewer')
    await wrapper.get('select[name="kind"]').setValue('aider')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(patch).toHaveBeenCalledWith('/api/projects/{project_id}/agents/{agent_id}', {
      params: { path: { project_id: 9, agent_id: 4 } },
      body: { title: 'Reviewer', kind: 'aider', reports_to: null, budget_micros: 2_500_000 },
    })
    expect(wrapper.emitted('saved')).toBeDefined()
  })
})
