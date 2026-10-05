import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'

import { createAppI18n } from '@/i18n'

const get = vi.fn().mockResolvedValue({
  data: [
    { kind: 'claude-code', pid: 21, pane: '%2', cwd: '/srv/work/site' },
    { kind: 'codex', pid: 42, pane: '%4', cwd: '/srv/work/site' },
  ],
})
const post = vi.fn().mockResolvedValue({ data: { approval_id: 8 } })
vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api')>()),
  api: { GET: (...args: unknown[]) => get(...args), POST: (...args: unknown[]) => post(...args) },
}))

import AdoptManagerForm from './AdoptManagerForm.vue'

it('uses only the selected CLI kind after a saved session is found running', async () => {
  const wrapper = mount(AdoptManagerForm, {
    props: { projectId: 7, kind: 'codex' },
    global: { plugins: [createAppI18n({ locale: 'en' })] },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="running-manager"]').findAll('option')).toHaveLength(2)
  expect((wrapper.get('[data-testid="running-manager"]').element as HTMLSelectElement).value).toBe(
    '42',
  )
  expect(wrapper.text()).toContain('The live conversation')
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(post).toHaveBeenCalledWith('/api/projects/{project_id}/adopt-manager', {
    params: { path: { project_id: 7 } },
    body: { pid: 42 },
  })
  expect(wrapper.emitted('requested')).toEqual([[8]])
})
