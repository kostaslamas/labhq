import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api'
import { renderApp, settle } from '@/shell/__fixtures__/render'

vi.mock('@/live', () => ({ useLiveTopic: vi.fn(), liveState: { value: 'idle' } }))

const report = {
  id: 5,
  text: 'Hire two reviewers.',
  refs: [],
  task_id: null,
  task_title: null,
  awaiting_decision: false,
  created_at: '2026-10-02T08:00:00Z',
}

const today = {
  since: '2026-10-01T09:00:00Z',
  until: '2026-10-02T09:00:00Z',
  ceo_report: report,
  deliverables: [],
  needs_you: { count: 0, approvals: [], questions: [], incidents: [], budget_warnings: [] },
  spend_without_output: [],
}

function room(overrides: Record<string, unknown> = {}) {
  return {
    id: 9,
    status: 'requested',
    project_id: 1,
    project_name: 'atlas',
    agenda: 'Hire two reviewers?',
    pinned_kind: 'report',
    pinned_id: 5,
    estimate_micros: 2_600_000,
    approval_id: 3,
    approval_status: 'pending',
    turns_used: 0,
    turn_cap: 12,
    waiting: null,
    end_reason: null,
    created_at: '2026-10-02T08:00:00Z',
    ended_at: null,
    ...overrides,
  }
}

const detail = {
  id: 9,
  kind: 'decision',
  status: 'running',
  messages: [
    {
      id: 1,
      source: 'agent',
      speaker: 'CEO',
      agent_id: 1,
      text: 'Two is too many?',
      created_at: '2026-10-02T08:01:00Z',
    },
    {
      id: 2,
      source: 'owner',
      speaker: 'Owner',
      agent_id: null,
      text: 'One only.',
      created_at: '2026-10-02T08:02:00Z',
    },
    {
      id: 3,
      source: 'agent',
      speaker: 'Boss',
      agent_id: 2,
      text: 'One works.',
      created_at: '2026-10-02T08:03:00Z',
    },
  ],
  decisions: [],
  action_items: [],
}

interface World {
  rooms?: unknown[]
  turns?: unknown[]
  reports?: unknown[]
}

function serve(world: World = {}) {
  const answers: Record<string, unknown> = {
    '/api/today': today,
    '/api/org/ceo': { id: 1, primary_kind: 'claude', backup_kind: null },
    '/api/org/ceo/messages': world.turns ?? [],
    '/api/org/ceo/reports': world.reports ?? [report],
    '/api/callcenter/rooms': world.rooms ?? [],
    '/api/callcenter/decisions': [],
    '/api/meetings/{meeting_id}': detail,
  }
  vi.spyOn(api, 'GET').mockImplementation(((path: string) =>
    Promise.resolve({ data: answers[path], response: new Response() })) as never)
  const queued = {
    id: 1,
    text: 'Why two?',
    reply: null,
    status: 'queued',
    created_at: '2026-10-02T08:05:00Z',
    actions: [],
  }
  return vi.spyOn(api, 'POST').mockResolvedValue({ data: queued, response: new Response() })
}

afterEach(() => {
  vi.restoreAllMocks()
})

function click(root: HTMLElement, testid: string): void {
  root.querySelector<HTMLElement>(`[data-testid="${testid}"]`)?.click()
}

describe('Call Center widget', () => {
  it('is on every authenticated page and not on the public ones', async () => {
    serve()
    for (const path of ['/today', '/projects', '/meetings', '/approvals']) {
      const { root } = await renderApp(path)
      await settle()
      expect(root.querySelector('[data-testid="callcenter-launcher"]'), path).not.toBeNull()
    }
    const { root } = await renderApp('/login')
    await settle()
    expect(root.querySelector('[data-testid="callcenter-launcher"]')).toBeNull()
  })

  it('opens and closes, and fills the screen at phone width', async () => {
    serve()
    const { root } = await renderApp('/today')
    await settle()
    expect(root.querySelector('[data-testid="callcenter-panel"]')).toBeNull()

    click(root, 'callcenter-launcher')
    await settle()
    const panel = root.querySelector('[data-testid="callcenter-panel"]')
    expect(panel).not.toBeNull()
    // Tailwind's `max-sm:` is the phone breakpoint; e2e measures the real viewport.
    expect(panel?.className).toContain('max-sm:inset-0')

    click(root, 'callcenter-close')
    await settle()
    expect(root.querySelector('[data-testid="callcenter-panel"]')).toBeNull()
  })

  it("shows a badge for the CEO's offer of a room", async () => {
    serve({ rooms: [room()] })
    const { root } = await renderApp('/today')
    await settle()

    expect(root.querySelector('[data-testid="callcenter-badge"]')?.textContent).toBe('1')
    click(root, 'callcenter-launcher')
    await settle()
    expect(root.querySelector('[data-testid="room-estimate"]')?.textContent).toContain('$2.60')
  })

  it('pins the proposal from a card and sends its id as context, not as text', async () => {
    const post = serve()
    const { root } = await renderApp('/today')
    await settle()

    click(root, 'discuss')
    await settle()
    expect(root.querySelector('[data-testid="callcenter-pin"]')?.textContent).toContain('#5')

    const box = root.querySelector<HTMLTextAreaElement>('[data-testid="callcenter-message"]')!
    box.value = 'Why two?'
    box.dispatchEvent(new Event('input'))
    await settle()
    click(root, 'callcenter-send')
    await settle()

    expect(post).toHaveBeenCalledWith('/api/org/ceo/messages', {
      body: {
        text: 'Why two?',
        context: {
          route: '/today',
          project_id: null,
          pinned: { kind: 'report', id: 5, options: ['show'] },
        },
      },
    })
  })

  it('draws the owner, the CEO and the manager in one labelled thread', async () => {
    serve({ rooms: [room({ status: 'running', turns_used: 2 })] })
    const { root } = await renderApp('/today')
    await settle()

    click(root, 'callcenter-launcher')
    await settle()
    click(root, 'tab-room')
    await settle()

    const speakers = [...root.querySelectorAll('[data-testid="room-speaker"]')].map(
      (node) => node.textContent,
    )
    expect(speakers).toEqual(['CEO', 'Owner', 'Boss'])
    expect(root.querySelector('[data-testid="room-turns"]')?.textContent).toBe('2/12')
  })

  it('says whom the room waits for and lets the owner send Esc to a tmux manager', async () => {
    const post = serve({
      rooms: [
        room({
          status: 'running',
          waiting: {
            agent_id: 2,
            agent_name: 'Boss',
            reason: 'finishing its current step',
            can_interrupt: true,
          },
        }),
      ],
    })
    const { root } = await renderApp('/today')
    await settle()
    click(root, 'callcenter-launcher')
    await settle()
    click(root, 'tab-room')
    await settle()

    expect(root.querySelector('[data-testid="room-waiting"]')?.textContent).toContain(
      'Waiting for Boss',
    )
    expect(root.querySelector('[data-testid="room-waiting"]')?.textContent).toContain(
      'finishing its current step',
    )
    click(root, 'room-interrupt')
    await settle()
    expect(post).toHaveBeenCalledWith('/api/agents/{agent_id}/keys', {
      params: { path: { agent_id: 2 } },
      body: { key: 'escape' },
    })
  })
})
