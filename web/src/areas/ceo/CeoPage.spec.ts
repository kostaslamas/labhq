import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppI18n } from '@/i18n'

const get = vi.fn()
const post = vi.fn()
const push = vi.fn()
vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: {
    GET: (...args: unknown[]) => get(...args),
    POST: (...args: unknown[]) => post(...args),
  },
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRouter: () => ({ push }),
  useRoute: () => ({ query: {} }),
}))

import CeoPage from './CeoPage.vue'

const stubs = { CeoAssignmentForm: true, SessionScan: true }
const plugins = [createAppI18n({ locale: 'en' })]
const found = { path: '/work/site', name: 'site' }

describe('the CEO tab', () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({ data: [] })
    post.mockReset()
    push.mockReset()
  })

  it('adds the folder as a project, then a manager of the chosen program', async () => {
    post
      .mockResolvedValueOnce({ data: { id: 4 } })
      .mockResolvedValueOnce({ data: { id: 9, approval_id: 2 } })
    const wrapper = mount(CeoPage, { global: { plugins, stubs } })
    await flushPromises()
    wrapper.findComponent({ name: 'SessionScan' }).vm.$emit('start', found, 'codex')
    await flushPromises()

    expect(post.mock.calls[0]).toEqual([
      '/api/projects',
      { body: { name: 'site', repo_path: '/work/site' } },
    ])
    expect(post.mock.calls[1]?.[1].body).toEqual({
      role: 'manager',
      title: 'site manager',
      kind: 'codex',
    })
    expect(push).toHaveBeenCalledWith({ name: 'project', params: { id: 4 } })
  })

  it('says so when the project cannot be created, and adds no agent', async () => {
    post.mockResolvedValueOnce({ data: undefined })
    const wrapper = mount(CeoPage, { global: { plugins, stubs } })
    await flushPromises()
    wrapper.findComponent({ name: 'SessionScan' }).vm.$emit('start', found, 'codex')
    await flushPromises()

    expect(post).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="ceo-start-failure"]').exists()).toBe(true)
    expect(push).not.toHaveBeenCalled()
  })
})
