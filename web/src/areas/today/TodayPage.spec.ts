import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import { useLiveTopic } from '@/live'
import { renderApp, settle } from '@/shell/__fixtures__/render'

import type { Today } from './useToday'

vi.mock('@/live', () => ({ useLiveTopic: vi.fn(), liveState: { value: 'idle' } }))

const answer: Today = {
  since: '2026-10-01T09:00:00Z',
  until: '2026-10-02T09:00:00Z',
  deliverables: [
    {
      task_id: 7,
      title: 'Add a HELLO file',
      project_id: 1,
      project_name: 'atlas',
      finished_at: '2026-10-02T08:00:00Z',
      branch: 'labhq/task-7-add-a-hello-file',
      commit_count: 2,
      approvals: [{ id: 9, type: 'push', status: 'executed', branch: null, commit: null }],
      cost_micros: 1_250_000,
    },
  ],
  needs_you: {
    count: 2,
    approvals: [
      {
        id: 3,
        type: 'push',
        risk_class: 'heavy',
        status: 'pending',
        created_at: '2026-10-02T08:30:00Z',
        task_id: 7,
        task_title: 'Add a HELLO file',
        project_id: 1,
        project_name: 'atlas',
      },
    ],
    questions: [],
    incidents: [],
    budget_warnings: [
      {
        id: 1,
        scope: 'project',
        scope_id: 1,
        name: 'atlas',
        spent_micros: 850_000,
        budget_micros: 1_000_000,
        created_at: '2026-10-02T08:00:00Z',
      },
    ],
  },
  spend_without_output: [
    {
      agent_id: 4,
      agent_title: 'Researcher',
      project_id: 2,
      project_name: 'beacon',
      cost_micros: 420_000,
    },
  ],
}

function respondWith(data: Today): void {
  vi.spyOn(api, 'GET').mockResolvedValue({ data, response: new Response() })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('TodayPage', () => {
  it('shows deliverables, what needs you and spend warnings in integer-micro amounts', async () => {
    respondWith(answer)
    const { root } = await renderApp('/today')
    await settle()

    expect(root.querySelector('[data-testid="needs-count"]')?.textContent).toBe('2')
    expect(root.querySelector('[data-testid="need-approval"]')?.textContent).toContain('heavy')
    expect(root.querySelector('[data-testid="need-budget"]')?.textContent).toContain('$0.85')
    expect(root.querySelector('[data-testid="spend-warning"]')?.textContent).toContain('$0.42')
    const delivered = root.querySelector('[data-testid="deliverable"]')?.textContent ?? ''
    expect(delivered).toContain('labhq/task-7-add-a-hello-file')
    expect(delivered).toContain('2 commits')
    expect(delivered).toContain('$1.25')
  })

  it('never lists agents at work', async () => {
    respondWith(answer)
    const { root } = await renderApp('/today')
    await settle()

    expect(root.querySelector('main')?.textContent?.toLowerCase()).not.toContain('working')
    expect(root.querySelector('main [data-state="working"]')).toBeNull()
  })

  it('refetches when any of its five topics changes', async () => {
    respondWith(answer)
    await renderApp('/today')
    await settle()

    const topics = vi.mocked(useLiveTopic).mock.calls.map(([topic]) => topic)
    expect(topics).toEqual(
      expect.arrayContaining(['approvals', 'tasks', 'questions', 'incidents', 'costs']),
    )
  })

  it('says so when nothing waits on the owner', async () => {
    respondWith({
      ...answer,
      deliverables: [],
      spend_without_output: [],
      needs_you: { count: 0, approvals: [], questions: [], incidents: [], budget_warnings: [] },
    })
    const { root } = await renderApp('/today')
    await settle()

    expect(root.querySelector('[data-testid="needs-you"]')?.textContent).toContain(
      'Nothing is waiting on you.',
    )
    expect(root.querySelector('[data-testid="spend-without-output"]')).toBeNull()
  })
})
