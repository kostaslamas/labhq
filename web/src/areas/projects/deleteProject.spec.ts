import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppI18n } from '@/i18n'

const get = vi.fn()
const del = vi.fn()
const push = vi.fn()
vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args), DELETE: (...args: unknown[]) => del(...args) },
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRouter: () => ({ push }),
}))
vi.mock('@/live', () => ({ useLiveTopic: () => undefined }))
vi.mock('@/areas/sessions/sessions', () => ({ loadSessions: () => Promise.resolve(null) }))

import ProjectPage from './ProjectPage.vue'

const view = {
  id: 7,
  name: 'site',
  status: 'active',
  budget: { budget_micros: null, spent_micros: 0, state: 'allow', used_percent: 0 },
  policy: { warn_percent: 80, stop_percent: 100, period_start: '2026-10-01T00:00:00Z' },
  team: [],
  tasks: {},
  deliverables: [],
  deliverables_total: 0,
}
const plugins = [createAppI18n({ locale: 'en' })]
const stubs = { RouterLink: { template: '<a><slot /></a>' } }

async function open() {
  const wrapper = mount(ProjectPage, { props: { id: '7' }, global: { plugins, stubs } })
  await flushPromises()
  return wrapper
}

describe('deleting a project', () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({ data: view, response: { status: 200 } })
    del.mockReset()
    push.mockReset()
  })

  it('asks first, then deletes and returns to the projects list', async () => {
    del.mockResolvedValue({ response: { ok: true, status: 204 } })
    const wrapper = await open()
    await wrapper.get('[data-testid="delete-project-button"]').trigger('click')
    expect(del).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="delete-project-confirm"]').trigger('click')
    await flushPromises()
    expect(del).toHaveBeenCalledWith('/api/projects/{project_id}', {
      params: { path: { project_id: 7 } },
    })
    expect(push).toHaveBeenCalledWith({ name: 'projects' })
  })

  it('keeps the page and says why when the project is busy', async () => {
    del.mockResolvedValue({
      error: { error: { code: 'project_busy', message: 'busy' } },
      response: { ok: false, status: 409 },
    })
    const wrapper = await open()
    await wrapper.get('[data-testid="delete-project-button"]').trigger('click')
    await wrapper.get('[data-testid="delete-project-confirm"]').trigger('click')
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('current runs')
  })
})
