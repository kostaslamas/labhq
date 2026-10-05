import { expect, test } from './support/auth.ts'
import { seedSummary } from './support/server.ts'

test('a running CLI in the project switches saved assignment to its tmux pane', async ({
  signedInPage: page,
}) => {
  const projectId = seedSummary().projects[1]!
  const base = `/api/projects/${projectId}`
  const candidate = { kind: 'claude-code', pid: 123, pane: '%2', cwd: '/srv/work/site' }
  await page.route(`**${base}/saved-sessions?*`, (route) =>
    route.fulfill({
      json: [{ kind: 'claude-code', session_id: 'saved', updated_at: '2026-10-01T10:00:00Z' }],
    }),
  )
  await page.route(`**${base}/running-managers`, (route) => route.fulfill({ json: [candidate] }))
  await page.route(`**${base}/assign-saved-session`, (route) =>
    route.fulfill({
      status: 409,
      json: { error: { code: 'agent_running', message: 'agent running' } },
    }),
  )
  let adoptedPid: number | undefined
  await page.route(`**${base}/adopt-manager`, async (route) => {
    adoptedPid = (route.request().postDataJSON() as { pid: number }).pid
    await route.fulfill({ status: 202, json: { approval_id: 42, warnings: [] } })
  })

  await page.goto(`/projects/${projectId}`)
  await page.getByTestId('assign-saved-session').click()
  await expect(page.getByTestId('choose-running-agent')).toBeVisible()
  await page.getByTestId('saved-session-choice').selectOption('saved')
  await page.getByTestId('saved-session-submit').click()
  await expect(page.getByTestId('running-manager')).toHaveValue('123')
  await expect(page.getByRole('status')).toContainText('The live conversation')
  await page.getByTestId('adopt-manager-submit').click()
  await expect(page.getByText('Assignment requested.')).toBeVisible()
  expect(adoptedPid).toBe(123)
})
