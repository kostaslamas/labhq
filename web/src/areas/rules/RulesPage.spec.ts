import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type components } from '@/api'
import { FakeSocket } from '@/live/__fixtures__/socket'
import { resetLiveConnection } from '@/live/useLiveTopic'
import { renderApp, settle } from '@/shell/__fixtures__/render'

type Rule = components['schemas']['HealthRuleItem']

const rule: Rule = {
  id: 7,
  name: 'Disk almost full',
  type: 'threshold',
  params: { metric: 'disk.percent', comparison: '>', value: 90 },
  action: 'notify',
  host: 'box',
  reason: 'The backup disk filled up twice in September.',
  created_by: 'agent:infra',
  enabled: true,
  created_at: '2026-10-01T08:00:00Z',
  updated_at: '2026-10-01T08:00:00Z',
  latest: {
    incident_id: 3,
    status: 'open',
    opened_at: '2026-10-02T09:00:00Z',
    resolved_at: null,
    details: {},
  },
}

// The page reads only `data`; the rest of openapi-fetch's result is not needed here.
function answer<T>(data: T): never {
  return { data, response: new Response() } as never
}

beforeEach(() => {
  FakeSocket.all = []
  vi.stubGlobal('WebSocket', FakeSocket)
  resetLiveConnection()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('rules page', () => {
  it('shows why each rule exists, who added it and its latest result', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(answer([rule]))
    const { root } = await renderApp('/projects/infra/rules')

    expect(root.querySelector('[data-testid="rule-reason"]')?.textContent).toContain(
      'backup disk filled up',
    )
    expect(root.querySelector('[data-testid="rule-creator"]')?.textContent).toContain('agent:infra')
    expect(root.querySelector('[data-state="failed"]')).not.toBeNull()
    // The page adds no sidebar item (plan §8.1).
    expect(root.querySelectorAll('[data-testid="nav-item"]')).toHaveLength(5)
  })

  it('disables a rule and shows it as disabled', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue(answer([rule]))
    const post = vi
      .spyOn(api, 'POST')
      .mockResolvedValue(answer({ ...rule, enabled: false, updated_at: '2026-10-02T10:00:00Z' }))
    const { root } = await renderApp('/projects/infra/rules')

    root.querySelector<HTMLButtonElement>('[data-testid="toggle-7"]')?.click()
    await settle()

    expect(post).toHaveBeenCalledWith('/api/health/rules/{rule_id}/enabled', {
      params: { path: { rule_id: 7 } },
      body: { enabled: false },
    })
    expect(root.querySelector('[data-testid="rule-disabled"]')).not.toBeNull()
    expect(root.querySelector('[data-testid="toggle-7"]')?.textContent).toContain('Enable')
  })

  it('reloads when the incidents topic changes', async () => {
    const get = vi.spyOn(api, 'GET').mockResolvedValue(answer([rule]))
    await renderApp('/projects/infra/rules')
    FakeSocket.latest().open()
    await settle()
    const before = get.mock.calls.length

    FakeSocket.latest().invalidate('incidents', '2')
    await settle()

    expect(get.mock.calls.length).toBe(before + 1)
  })
})
