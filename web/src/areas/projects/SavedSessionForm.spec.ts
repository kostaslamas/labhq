import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'

import { createAppI18n } from '@/i18n'

const get = vi.fn()
const post = vi.fn()
vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args), POST: (...args: unknown[]) => post(...args) },
}))

import SavedSessionForm from './SavedSessionForm.vue'

beforeEach(() => {
  get.mockReset().mockImplementation((path: string) =>
    path === '/api/agent-kinds'
      ? Promise.resolve({
          data: [
            { name: 'claude', adapter: 'claude', available: true, display_name: 'Claude SDK' },
            { name: 'codex', adapter: 'tmux', available: true, display_name: 'Codex' },
          ],
        })
      : path === '/api/projects/{project_id}/running-managers'
        ? Promise.resolve({ data: [] })
        : Promise.resolve({
            data: [
              { kind: 'codex', session_id: 'first', updated_at: '2026-10-01T10:00:00Z' },
              { kind: 'codex', session_id: 'second', updated_at: '2026-10-02T10:00:00Z' },
            ],
          }),
  )
  post.mockReset().mockResolvedValue({ data: { approval_id: 42 } })
})

it('offers the live tmux agent and switches to it when saved assignment is blocked', async () => {
  get.mockImplementation((path: string) =>
    path === '/api/agent-kinds'
      ? Promise.resolve({ data: [{ name: 'codex', adapter: 'tmux', available: true }] })
      : path === '/api/projects/{project_id}/running-managers'
        ? Promise.resolve({
            data: [{ kind: 'codex', pid: 123, pane: '%4', cwd: '/srv/work/site' }],
          })
        : Promise.resolve({
            data: [{ kind: 'codex', session_id: 'saved', updated_at: '2026-10-01T10:00:00Z' }],
          }),
  )
  post.mockResolvedValue({ error: { error: { code: 'agent_running' } } })
  const wrapper = mount(SavedSessionForm, {
    props: { projectId: 7 },
    global: { plugins: [createAppI18n({ locale: 'en' })] },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="choose-running-agent"]').text()).toBe('Choose running agent')
  await wrapper.get('[data-testid="saved-session-choice"]').setValue('saved')
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(wrapper.emitted('running')).toEqual([['codex']])
  expect(wrapper.emitted('requested')).toBeUndefined()
})

it('lets the owner choose an exact saved session of the selected CLI', async () => {
  const wrapper = mount(SavedSessionForm, {
    props: { projectId: 7 },
    global: { plugins: [createAppI18n({ locale: 'en' })] },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="saved-session-kind"]').element).toHaveProperty('value', 'codex')
  expect(get).toHaveBeenCalledWith('/api/projects/{project_id}/saved-sessions', {
    params: { path: { project_id: 7 }, query: { kind: 'codex' } },
  })
  await wrapper.get('[data-testid="saved-session-choice"]').setValue('second')
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(post).toHaveBeenCalledWith('/api/projects/{project_id}/assign-saved-session', {
    params: { path: { project_id: 7 } },
    body: { kind: 'codex', session_id: 'second' },
  })
  expect(wrapper.emitted('requested')).toEqual([[42]])
})
