import { fileURLToPath } from 'node:url'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'

import type { components } from '../src/api/schema'
import { expect, test } from './support/auth.ts'

type ProjectView = components['schemas']['ProjectView']

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))
const NAME = 'zz-e2e-added'

test.describe.configure({ mode: 'serial' })

test('a path that is not a directory is refused in words', async ({ signedInPage: page }) => {
  await page.goto('/projects')
  await page.getByTestId('add-project').click()
  await page.getByLabel('Name').fill('zz-e2e-refused')
  await page.getByLabel('Project folder').fill('/nonexistent/labhq-e2e')
  await page.getByTestId('add-project-submit').click()

  await expect(page.getByTestId('form-error')).toHaveText(
    'That path is not an existing, readable folder.',
  )
  await expect(page).toHaveURL(/\/projects$/)
})

test('a plain folder can become a project without Git', async ({ signedInPage: page }) => {
  const folder = await mkdtemp(join(tmpdir(), 'labhq-e2e-plain-'))
  try {
    await page.goto('/projects')
    await page.getByTestId('add-project').click()
    await page.getByLabel('Name').fill('zz-e2e-plain')
    await page.getByLabel('Project folder').fill(folder)
    await page.getByTestId('add-project-submit').click()

    await expect(page).toHaveURL(/\/projects\/\d+$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('zz-e2e-plain')
  } finally {
    await rm(folder, { recursive: true, force: true })
  }
})

test('a project and an agent added in the UI appear, and the agent starts only after approval', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects')
  await page.getByTestId('add-project').click()
  await page.getByLabel('Name').fill(NAME)
  await expect(page.getByRole('button', { name: 'Browse server folders' })).toHaveCount(0)
  const browser = page.getByTestId('repository-browser')
  await page
    .getByLabel('Project folder')
    .fill(`${dirname(repoRoot)}/${basename(repoRoot).slice(0, 3)}`)
  await expect(
    browser.getByRole('button', { name: `${basename(repoRoot)}/`, exact: true }),
  ).toBeVisible()
  await browser.getByRole('button', { name: `${basename(repoRoot)}/`, exact: true }).click()
  await expect(page.getByLabel('Project folder')).toHaveValue(resolve(repoRoot))
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

  await page.goto(`/projects/${projectId}`)
  await page.getByTestId('edit-agent').click()
  await page.getByTestId('edit-agent-form').getByLabel('Title').fill('E2E reviewer')
  await page.getByTestId('edit-agent-form').getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByTestId('team-title')).toHaveText(['E2E reviewer'])
  const updated = await page.request.get(`/api/projects/${projectId}`)
  const updatedView = (await updated.json()) as ProjectView
  expect(updatedView.team).toHaveLength(1)
  expect(updatedView.team[0]?.title).toBe('E2E reviewer')
})
