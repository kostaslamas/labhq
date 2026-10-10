import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppI18n } from '@/i18n'

const get = vi.fn()
const replace = vi.fn()
const query: Record<string, string> = {}
vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args) },
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('vue-router')>()),
  useRoute: () => ({ query }),
  useRouter: () => ({ replace, push: vi.fn() }),
}))
vi.mock('@/live', () => ({ useLiveTopic: () => undefined }))

import ProjectsPage from './ProjectsPage.vue'

const plugins = [createAppI18n({ locale: 'en' })]
const stubs = { RouterLink: { template: '<a><slot /></a>' }, AddProjectForm: true }

async function open() {
  const wrapper = mount(ProjectsPage, { global: { plugins, stubs } })
  await flushPromises()
  return wrapper
}

describe('projects page links', () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue({ data: { items: [], next_cursor: null } })
    replace.mockReset()
    for (const key of Object.keys(query)) delete query[key]
  })

  it('sends an old scan-panel link to the CEO tab', async () => {
    query.panel = 'scan'
    await open()
    expect(replace).toHaveBeenCalledWith({ name: 'ceo', query: { panel: 'scan' } })
  })

  it('opens the add form with the folder a found project came with', async () => {
    query.add = '/work/site'
    query.name = 'site'
    const wrapper = await open()
    const form = wrapper.findComponent({ name: 'AddProjectForm' })
    expect(form.exists()).toBe(true)
    expect(form.props('initialPath')).toBe('/work/site')
    expect(form.props('initialName')).toBe('site')
  })

  it('does not hold the CEO settings any more', async () => {
    const wrapper = await open()
    expect(wrapper.find('[data-testid="session-scan"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ceo-assignment"]').exists()).toBe(false)
  })
})
