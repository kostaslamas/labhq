import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { fakeServer } from '@/auth/__fixtures__/server'
import { setAuthClient } from '@/auth/client'
import { createAppI18n } from '@/i18n'

import ProjectSessions from './ProjectSessions.vue'
import SessionsPage from './SessionsPage.vue'
import type { ScannedProject, SessionsView } from './sessions'

const stubs = { RouterLink: { template: '<a><slot /></a>' } }

const git = {
  branch: 'main',
  dirty_files: 2,
  last_commit_subject: 'first',
  last_commit_at: '2026-10-01T10:00:00Z',
  open_pr: null,
}
const project: ScannedProject = {
  root: '/home/o/code/party',
  name: 'party',
  has_repo: true,
  project_id: null,
  git,
  sessions: [
    {
      tool: 'claude-code',
      session_id: 'abc',
      state: 'idle',
      idle_seconds: 7200,
      last_activity: '2026-10-10T06:00:00Z',
      pid: null,
      resumable: true,
      proposal: { action: 'continue', reason: 'recent work' },
    },
    {
      tool: 'aider',
      session_id: null,
      state: 'waiting for input',
      idle_seconds: 60,
      last_activity: null,
      pid: 77,
      resumable: true,
      proposal: { action: 'close', reason: 'quiet for 12 h' },
    },
  ],
}
const view: SessionsView = {
  scanned_at: '2026-10-10T08:00:00Z',
  left_out: 2,
  projects: [project],
  folders: [{ folder: '/home/o/code', projects: ['/a', '/b'] }],
  tools: [
    { tool: 'claude-code', logged_in: true, account: null, plan: 'allow', plan_used_percent: 10 },
  ],
}

function mountWith(routes: Parameters<typeof fakeServer>[0], component: object, props = {}) {
  const server = fakeServer(routes)
  setAuthClient(server.client)
  const wrapper = mount(component, {
    props,
    global: { plugins: [createAppI18n({ locale: 'en' })], stubs },
  })
  return { wrapper, ...server }
}

describe('project sessions', () => {
  it('shows git facts, state, idle time and the proposed action per session', () => {
    const { wrapper } = mountWith({}, ProjectSessions, { project })

    expect(wrapper.get('[data-testid="git-facts"]').text()).toContain('main · 2 dirty files')
    const [first, second] = wrapper.findAll('[data-testid="session-row"]')
    expect(first?.text()).toContain('idle 2 h')
    expect(first?.get('[data-testid="proposal"]').text()).toContain('continue — recent work')
    expect(second?.text()).toContain('waiting for input')
    // Only a running process can be closed.
    expect(first?.find('[data-testid="close"]').exists()).toBe(false)
    expect(second?.find('[data-testid="close"]').exists()).toBe(true)
  })

  it('continues a saved session by its id and a running one by its pid', async () => {
    const { wrapper, requests } = mountWith(
      {
        'POST /api/inventory/actions/continue': () => ({
          status: 201,
          body: { approval_id: 9, task_id: null, summary: 'Continue claude-code.' },
        }),
      },
      ProjectSessions,
      { project },
    )

    const rows = wrapper.findAll('[data-testid="session-row"]')
    await rows[0]?.get('[data-testid="continue"]').trigger('click')
    await flushPromises()
    await rows[1]?.get('[data-testid="continue"]').trigger('click')
    await flushPromises()

    expect(requests.map((r) => r.body)).toEqual([
      { project: 'party', session_id: 'abc' },
      { project: 'party', pid: 77 },
    ])
    expect(wrapper.get('[data-testid="approval-link"]').text()).toBe('Review approval 9')
  })

  it('asks to close by pid and shows the server reason when refused', async () => {
    const { wrapper, requests } = mountWith(
      {
        'POST /api/inventory/actions/close': () => ({
          status: 422,
          body: {
            error: {
              code: 'inventory_action_refused',
              message: 'aider is in the middle of a turn; it was not closed',
              details: null,
            },
          },
        }),
      },
      ProjectSessions,
      { project },
    )

    await wrapper.get('[data-testid="close"]').trigger('click')
    await flushPromises()

    expect(requests[0]?.body).toEqual({ project: 'party', pid: 77 })
    expect(wrapper.get('[data-testid="action-error"]').text()).toContain('middle of a turn')
  })

  it('shows the analysis estimate before anything runs', async () => {
    const { wrapper } = mountWith(
      {
        'POST /api/inventory/actions/analyse': () => ({
          status: 201,
          body: {
            approval_id: 4,
            task_id: null,
            summary: 'About 12000 tokens (~$0.04) on ollama. Approve approval 4 to start.',
          },
        }),
      },
      ProjectSessions,
      { project },
    )

    await wrapper.get('[data-testid="analyse"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="action-summary"]').text()).toContain('Approve approval 4')
  })
})

describe('sessions page', () => {
  it('lists the last scan, the tools and the folder-manager proposals', async () => {
    const { wrapper } = mountWith(
      { 'GET /api/inventory/sessions': () => ({ body: view }) },
      SessionsPage,
    )
    await flushPromises()

    expect(wrapper.get('[data-testid="last-scan"]').text()).toContain('2 sessions left out')
    expect(wrapper.get('[data-testid="tools"]').text()).toContain('claude-code: logged in')
    expect(wrapper.findAll('[data-testid="scanned-party"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="folder-proposals"]').text()).toContain('2 projects')
  })

  it('scans by itself when the server has not scanned yet, and again on request', async () => {
    const empty: SessionsView = {
      scanned_at: null,
      left_out: 0,
      projects: [],
      folders: [],
      tools: [],
    }
    let scans = 0
    const { wrapper, requests } = mountWith(
      {
        'GET /api/inventory/sessions': () => ({ body: scans === 0 ? empty : view }),
        'POST /api/inventory/scan': () => {
          scans += 1
          return { body: {} }
        },
      },
      SessionsPage,
    )
    await flushPromises()

    expect(scans).toBe(1)
    expect(wrapper.findAll('[data-testid="scanned-party"]')).toHaveLength(1)
    await wrapper.get('[data-testid="scan-now-sessions"]').trigger('click')
    await flushPromises()
    expect(requests.filter((r) => r.method === 'POST')).toHaveLength(2)
  })

  it('asks for a folder manager as an approval', async () => {
    const { wrapper, requests } = mountWith(
      {
        'GET /api/inventory/sessions': () => ({ body: view }),
        'POST /api/inventory/actions/folder': () => ({
          status: 201,
          body: { approval_id: 3, task_id: null, summary: 'Folder manager for code.' },
        }),
      },
      SessionsPage,
    )
    await flushPromises()

    await wrapper.get('[data-testid="folder-manager"]').trigger('click')
    await flushPromises()

    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({ folder: '/home/o/code' })
    expect(wrapper.get('[data-testid="folder-result"]').text()).toContain('Review approval 3')
  })
})
