import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import { useLiveTopic } from '@/live'
import { renderApp, settle } from '@/shell/__fixtures__/render'

import type { RunCapacity } from './useCapacity'
import type { Today } from './useToday'

vi.mock('@/live', () => ({ useLiveTopic: vi.fn(), liveState: { value: 'idle' } }))

const answer: Today = {
  since: '2026-10-01T09:00:00Z',
  until: '2026-10-02T09:00:00Z',
  ceo_report: null,
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

const capacity: RunCapacity = {
  running: 1,
  max_running: 3,
  free_memory_percent: 62.5,
  min_free_memory_percent: 15,
  paused_for_memory: false,
  waiting: 0,
}

function respondWith(
  data: Today,
  reading: RunCapacity = capacity,
  found: { path: string; name: string }[] = [],
): void {
  // The page reads three endpoints; each gets its own answer.
  const bodies: Record<string, unknown> = {
    '/api/capacity': reading,
    '/api/inventory/new-projects': found,
  }
  const answer = (path: string) =>
    Promise.resolve({ data: (bodies[path] ?? data) as Today, response: new Response() })
  vi.spyOn(api, 'GET').mockImplementation(answer)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('TodayPage', () => {
  it('lists the projects the automatic scan found, and nothing when it found none', async () => {
    respondWith(answer, capacity, [{ path: '/home/o/code/site', name: 'site' }])
    const { root } = await renderApp('/today')
    await settle()

    const card = root.querySelector('[data-testid="new-projects"]')
    expect(card?.textContent).toContain('1 new project found')
    expect(card?.textContent).toContain('/home/o/code/site')
    expect(root.querySelector('[data-testid="new-projects-link"]')).not.toBeNull()
  })

  it('shows no new-projects card while the scan has announced nothing', async () => {
    respondWith(answer)
    const { root } = await renderApp('/today')
    await settle()

    expect(root.querySelector('[data-testid="new-projects"]')).toBeNull()
  })

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

  it('shows run capacity and free memory at the top, calm while admission runs', async () => {
    respondWith(answer)
    const { root } = await renderApp('/today')
    await settle()

    const card = root.querySelector('[data-testid="capacity"]')
    expect(card?.getAttribute('data-paused')).toBe('false')
    expect(root.querySelector('[data-testid="capacity-running"]')?.textContent).toContain('1 / 3')
    expect(root.querySelector('[data-testid="capacity-memory"]')?.textContent).toContain('62.5%')
    expect(root.querySelector('[data-testid="capacity-paused"]')).toBeNull()
    const needs = root.querySelector('[data-testid="needs-you"]')
    expect(card && needs && card.compareDocumentPosition(needs)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })

  it('warns while admission is paused for memory', async () => {
    respondWith(answer, {
      ...capacity,
      free_memory_percent: 9.5,
      paused_for_memory: true,
      waiting: 4,
    })
    const { root } = await renderApp('/today')
    await settle()

    expect(root.querySelector('[data-testid="capacity"]')?.getAttribute('data-paused')).toBe('true')
    const warning = root.querySelector('[data-testid="capacity-paused"]')
    expect(warning?.getAttribute('role')).toBe('alert')
    expect(warning?.textContent).toContain('9.5%')
    expect(warning?.textContent).toContain('15%')
    expect(root.querySelector('[data-testid="capacity-waiting"]')?.textContent).toContain('4')
  })

  it("opens with the CEO's latest report", async () => {
    respondWith({
      ...answer,
      ceo_report: {
        id: 5,
        text: 'T7 Add a HELLO file is done and waits for your decision.',
        refs: ['T7'],
        task_id: 7,
        task_title: 'Add a HELLO file',
        awaiting_decision: true,
        created_at: '2026-10-02T08:45:00Z',
      },
    })
    const { root } = await renderApp('/today')
    await settle()

    const section = root.querySelector('[data-testid="today-ceo-report"]')
    const needs = root.querySelector('[data-testid="needs-you"]')
    expect(section?.textContent).toContain('T7 Add a HELLO file is done')
    expect(section?.querySelector('[data-testid="report-accept"]')).not.toBeNull()
    // At the top: before what needs the owner.
    expect(section && needs && section.compareDocumentPosition(needs)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
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
