import type { Route } from '@playwright/test'

import { expect, test } from './support/auth.ts'

// The seeded server has no tmux pane, so the pane-facing routes are answered here; what the
// spec proves is what the page shows for each kind of agent and what it sends.
const CEO_ID = 41

function json(route: Route, body: unknown): Promise<void> {
  return route.fulfill({ json: body })
}

test.beforeEach(async ({ signedInPage: page }) => {
  await page.route('**/api/org/ceo', (route) =>
    json(route, { id: CEO_ID, primary_kind: 'claude-code', backup_kind: null }),
  )
  await page.route('**/api/org/ceo/messages', (route) => json(route, []))
  await page.route('**/api/org/ceo/reports', (route) => json(route, []))
})

test('the Call Center offers Esc and Shift+Tab for a tmux agent and sends the named key', async ({
  signedInPage: page,
}) => {
  const sent: unknown[] = []
  await page.route(`**/api/agents/${CEO_ID}/keys`, (route) => {
    if (route.request().method() === 'POST') {
      sent.push(route.request().postDataJSON())
      return json(route, { key: 'shift_tab', screen: 'mode: plan' })
    }
    return json(route, { keys: ['escape', 'shift_tab', 'ctrl_c'], live: true })
  })
  await page.route(`**/api/agents/${CEO_ID}/screen`, (route) =>
    json(route, { screen: 'mode: plan' }),
  )
  await page.goto('/today')
  await page.getByTestId('callcenter-launcher').click()
  await page.getByTestId('callcenter-keys').click()

  await expect(page.getByTestId('control-key-escape')).toHaveText('Esc (stop)')
  await page.getByTestId('control-key-shift_tab').click()

  await expect(page.getByTestId('control-screen')).toContainText('mode: plan')
  expect(sent).toEqual([{ key: 'shift_tab' }])
})

test('the Call Center shows no key buttons for an agent without a tmux pane', async ({
  signedInPage: page,
}) => {
  await page.route(`**/api/agents/${CEO_ID}/keys`, (route) =>
    json(route, { keys: [], live: false }),
  )
  await page.goto('/today')
  await page.getByTestId('callcenter-launcher').click()
  await page.getByTestId('callcenter-keys').click()

  await expect(page.getByTestId('chat-thread')).toBeVisible()
  await expect(page.getByTestId('control-keys')).toHaveCount(0)
})
