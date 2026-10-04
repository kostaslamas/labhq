import { fileURLToPath } from 'node:url'

import type { components } from '../src/api/schema'
import { expect, test } from './support/auth.ts'

type ProjectView = components['schemas']['ProjectView']

// Any git repository with a commit on this machine; the server only reads its HEAD.
const repoRoot = fileURLToPath(new URL('../../', import.meta.url))
const NAME = 'zz-e2e-added'

test.describe.configure({ mode: 'serial' })

test('a repository that is not a git repository with a commit is refused in words', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects')
  await page.getByTestId('add-project').click()
  await page.getByLabel('Name').fill('zz-e2e-refused')
  await page.getByLabel('Repository path').fill('/nonexistent/labhq-e2e')
  await page.getByTestId('add-project-submit').click()

  await expect(page.getByTestId('form-error')).toHaveText(
    'That path is not a git repository with a commit.',
  )
  await expect(page).toHaveURL(/\/projects$/)
})

test('a project and an agent added in the UI appear, and the agent starts only after approval', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects')
  await page.getByTestId('add-project').click()
  await page.getByLabel('Name').fill(NAME)
  await page.getByLabel('Repository path').fill(repoRoot)
  await page.getByLabel('Monthly budget in USD (optional)').fill('2.50')
  await page.getByTestId('add-project-submit').click()

  // The new project's page opens, with its budget.
  await expect(page).toHaveURL(/\/projects\/\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(NAME)
  const projectId = Number(page.url().split('/').at(-1))

  await page.getByTestId('add-agent').click()
  await page.getByLabel('Title').fill('E2E coder')
  // Kinds come from the server's registry; only the ones with a program here are selectable.
  const kind = page.getByTestId('agent-kind')
  await expect(kind.locator('option')).not.toHaveCount(0)
  await kind.selectOption('aider')
  await page.getByTestId('add-agent-submit').click()

  await expect(page.getByTestId('agent-waiting')).toBeVisible()
  await expect(page.getByTestId('team-title')).toHaveText(['E2E coder'])

  const status = async () => {
    const response = await page.request.get(`/api/projects/${projectId}`)
    const view = (await response.json()) as ProjectView
    return view.team[0]?.status
  }
  expect(await status()).toBe('pending_approval')

  // The agent is back on the Projects page, and its approval is waiting in Approvals.
  await page.goto('/projects')
  await expect(page.getByRole('link', { name: NAME, exact: true })).toBeVisible()
  await page.goto('/approvals')
  await page.getByTestId('approval-list').getByText('Add an agent').first().click()
  await page.getByTestId('approve').click()
  await expect(page.getByTestId('decision')).toBeVisible()

  await expect.poll(status).toBe('active')
})
