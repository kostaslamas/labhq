import type { Page, Route } from '@playwright/test'

import { expect, test } from './support/auth.ts'

const PHONE = { width: 390, height: 844 }

// The seeded server runs no model, so the decision room's own endpoints are answered here;
// the room's engine is covered by the Python tests. What these specs prove is the widget.
const ROOM = {
  id: 9,
  status: 'requested',
  project_id: 1,
  project_name: 'atlas',
  agenda: 'Hire two reviewers?',
  pinned_kind: 'report',
  pinned_id: 77,
  estimate_micros: 2_600_000,
  approval_id: 3,
  approval_status: 'pending',
  turns_used: 0,
  turn_cap: 12,
  waiting: null,
  end_reason: null,
  created_at: '2026-10-02T08:00:00Z',
  ended_at: null,
}

function json(route: Route, body: unknown): Promise<void> {
  return route.fulfill({ json: body })
}

// Today as the server serves it, with the latest report replaced. A fetch still in flight when
// the test ends is dropped, not reported as a failure.
async function serveTodayWith(page: Page, report: unknown): Promise<void> {
  await page.route('**/api/today', async (route) => {
    try {
      const response = await route.fetch()
      const today = (await response.json()) as Record<string, unknown>
      await json(route, { ...today, ceo_report: report })
    } catch {
      // The page closed under the request.
    }
  })
}

async function overflowsHorizontally(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )
}

test('the widget is on every page, opens and closes, and the CEO page is gone', async ({
  signedInPage: page,
}) => {
  for (const path of ['/today', '/projects', '/meetings', '/approvals']) {
    await page.goto(path)
    await expect(page.getByTestId('callcenter-launcher'), path).toBeVisible()
  }
  await expect(page.getByTestId('nav-item').filter({ hasText: 'CEO' })).toHaveCount(0)
  await page.goto('/ceo')
  await expect(page).toHaveURL(/\/today$/)

  const launcher = page.getByTestId('callcenter-launcher')
  await expect(page.getByTestId('callcenter-panel')).toHaveCount(0)
  await launcher.click()
  await expect(page.getByTestId('callcenter-panel')).toBeVisible()
  // It stays open while the owner moves between pages.
  await page.getByTestId('nav-item').filter({ hasText: 'Projects' }).click()
  await expect(page.getByTestId('callcenter-panel')).toBeVisible()
  await page.getByTestId('callcenter-close').click()
  await expect(page.getByTestId('callcenter-panel')).toHaveCount(0)
})

test('on a phone the widget fills the screen and the page does not scroll sideways', async ({
  signedInPage: page,
}) => {
  await page.setViewportSize(PHONE)
  await page.goto('/today')
  await page.getByTestId('callcenter-launcher').click()

  const box = await page.getByTestId('callcenter-panel').boundingBox()
  expect(box).toEqual({ x: 0, y: 0, ...PHONE })
  expect(await overflowsHorizontally(page)).toBe(false)
  await page.getByTestId('callcenter-close').click()
  await expect(page.getByTestId('callcenter-panel')).toHaveCount(0)
})

test('a report waiting for the owner puts a badge on the widget; Discuss pins it', async ({
  signedInPage: page,
}) => {
  const report = {
    id: 77,
    text: 'Ship the discussion page is done and waits for your decision.',
    refs: [],
    task_id: null,
    task_title: null,
    awaiting_decision: true,
    created_at: ROOM.created_at,
  }
  // Specs share one database and Today shows its latest report, so this one is served here.
  await page.route('**/api/org/ceo', (route) =>
    json(route, { id: 41, primary_kind: 'claude-code', backup_kind: null }),
  )
  await page.route('**/api/org/ceo/reports', (route) => json(route, [report]))
  await serveTodayWith(page, report)
  let body: { text: string; context: { pinned: { kind: string; id: number } } } | undefined
  // The server would list the queued turn on every reload; other specs make live updates.
  const turns: unknown[] = []
  await page.route('**/api/org/ceo/messages', async (route) => {
    if (route.request().method() !== 'POST') return json(route, turns)
    body = route.request().postDataJSON() as typeof body
    const turn = {
      id: 1,
      text: body?.text,
      reply: null,
      status: 'queued',
      created_at: new Date().toISOString(),
      actions: [],
    }
    turns.push(turn)
    return route.fulfill({ status: 202, json: turn })
  })
  await page.goto('/today')
  await expect(page.getByTestId('callcenter-badge')).toHaveText('1')

  await page.getByTestId('ceo-report').getByTestId('discuss').click()
  const pin = page.getByTestId('callcenter-pin')
  await expect(pin).toContainText('CEO report #77')
  await page.getByTestId('callcenter-message').fill('Why this one?')
  await page.getByTestId('callcenter-send').click()
  await expect(page.getByTestId('chat-owner')).toContainText('Why this one?')

  // The proposal travels as structured context; the typed words are only the question.
  expect(body?.text).toBe('Why this one?')
  expect(body?.context.pinned).toMatchObject({ kind: 'report', id: 77 })
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('the CEO offers a decision room; the owner sees the cost and starts it', async ({
  signedInPage: page,
}) => {
  await page.route('**/api/callcenter/rooms', (route) => json(route, [ROOM]))
  let started = false
  await page.route('**/api/callcenter/rooms/9/start', (route) => {
    started = true
    return json(route, { ...ROOM, status: 'running' })
  })
  await page.goto('/today')
  await expect(page.getByTestId('callcenter-badge')).toBeVisible()
  await page.getByTestId('callcenter-launcher').click()

  await expect(page.getByTestId('room-offer')).toContainText('atlas')
  await expect(page.getByTestId('room-estimate')).toContainText('$2.60')
  await page.getByTestId('room-start').click()
  await expect.poll(() => started).toBe(true)
})

test('the owner, the CEO and the manager share one thread, and a busy tmux manager can be stopped', async ({
  signedInPage: page,
}) => {
  const running = {
    ...ROOM,
    status: 'running',
    turns_used: 2,
    waiting: {
      agent_id: 2,
      agent_name: 'Boss',
      reason: 'finishing its current step',
      can_interrupt: true,
    },
  }
  await page.route('**/api/callcenter/rooms', (route) => json(route, [running]))
  await page.route('**/api/meetings/9', (route) =>
    json(route, {
      id: 9,
      kind: 'decision',
      status: 'running',
      project_id: 1,
      project_name: 'atlas',
      created_at: ROOM.created_at,
      started_at: ROOM.created_at,
      channel: null,
      agenda: ROOM.agenda,
      end_reason: null,
      ended_at: null,
      participants: [],
      decisions: [],
      action_items: [],
      messages: [
        {
          id: 1,
          source: 'agent',
          speaker: 'CEO',
          agent_id: 1,
          text: 'Two reviewers?',
          created_at: ROOM.created_at,
        },
        {
          id: 2,
          source: 'owner',
          speaker: 'Owner',
          agent_id: null,
          text: 'One is enough.',
          created_at: ROOM.created_at,
        },
        {
          id: 3,
          source: 'system',
          speaker: 'system',
          agent_id: null,
          text: 'Waiting for Boss: finishing its current step.',
          created_at: ROOM.created_at,
        },
      ],
    }),
  )
  const keys: unknown[] = []
  await page.route('**/api/agents/2/keys', (route) => {
    keys.push(route.request().postDataJSON())
    return json(route, { key: 'escape', screen: '' })
  })
  await page.goto('/today')
  await page.getByTestId('callcenter-launcher').click()
  await page.getByTestId('tab-room').click()

  await expect(page.getByTestId('room-speaker')).toHaveText(['CEO', 'Owner', 'labhq'])
  await expect(page.getByTestId('room-waiting')).toContainText('Waiting for Boss')
  await expect(page.getByTestId('room-waiting')).toContainText('finishing its current step')
  await page.getByTestId('room-interrupt').click()
  await expect.poll(() => keys).toEqual([{ key: 'escape' }])
})

test('what a room decided shows on the proposal card as "Decided:"', async ({
  signedInPage: page,
}) => {
  await serveTodayWith(page, {
    id: 77,
    text: 'Hire two reviewers.',
    refs: [],
    task_id: null,
    task_title: null,
    awaiting_decision: false,
    created_at: ROOM.created_at,
  })
  await page.route('**/api/callcenter/decisions', (route) =>
    json(route, [
      {
        meeting_id: 9,
        pinned_kind: 'report',
        pinned_id: 77,
        decisions: ['Hire one reviewer'],
        actions: [{ text: 'Open the role', approval_id: 4, approval_status: 'pending' }],
        ended_at: ROOM.created_at,
      },
    ]),
  )
  await page.goto('/today')

  const decided = page.getByTestId('ceo-report').getByTestId('decided')
  await expect(decided).toContainText('Decided: Hire one reviewer')
  await expect(decided).toContainText('Open the role')
  await expect(decided).toContainText('waits for your approval')
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})
