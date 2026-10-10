import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test } from './support/auth.ts'
import { CLAUDE_DIR_ENV } from './support/server.ts'

// Both specs change the scan folders, which belong to the one server every spec shares, so they
// live in one file: a file runs on one worker, in order.
function repository(path: string): void {
  mkdirSync(path, { recursive: true })
  execFileSync('git', ['init', '-q', '-b', 'main'], { cwd: path })
  execFileSync(
    'git',
    [
      '-c',
      'user.email=e2e@example.test',
      '-c',
      'user.name=e2e',
      'commit',
      '-q',
      '--allow-empty',
      '-m',
      'start',
    ],
    { cwd: path },
  )
}

test('the owner sets a folder on /ceo, finds projects in it, adds one and skips another', async ({
  signedInPage: page,
}) => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'labhq-scan-')))
  repository(join(root, 'wanted-site'))
  repository(join(root, 'skipped-site'))

  await page.goto('/ceo?panel=scan')
  await expect(page.getByTestId('machine-wide')).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true)

  // The folder is set with a passkey; the first look runs once, by itself.
  await page.getByTestId('root-path').fill(root)
  await page.getByTestId('add-button').click()
  await expect(page.getByTestId(`root-${root}`)).toBeVisible()
  await expect(page.getByTestId('found-wanted-site')).toContainText('git')
  await expect(page.getByTestId('found-skipped-site')).toBeVisible()
  await expect(page.getByTestId('left-out')).toBeVisible()

  // "Not interested" records an exclusion and the project leaves the list for good.
  await page.getByTestId('found-skipped-site').getByTestId('found-skip').click()
  await expect(page.getByTestId('found-skipped-site')).toHaveCount(0)
  await page.getByTestId('scan-now').click()
  await expect(page.getByTestId('found-wanted-site')).toBeVisible()
  await expect(page.getByTestId('found-skipped-site')).toHaveCount(0)

  // "Add project" opens the existing form with the folder filled in.
  await page.getByTestId('found-wanted-site').getByTestId('found-add').click()
  await expect(page.getByTestId('add-project-form').locator('input[name="repo_path"]')).toHaveValue(
    join(root, 'wanted-site'),
  )
  await page.getByTestId('add-project-submit').click()
  await expect(page).toHaveURL(/\/projects\/\d+$/)

  // Leave the shared seed as found for the specs that run after this one.
  await page.goto('/ceo')
  await expect(page.getByTestId('roots')).toBeVisible()
  const removals = page.getByTestId('session-scan').getByRole('button', { name: 'Remove' })
  for (let left = await removals.count(); left > 0; left--) {
    await removals.first().click()
    await expect(removals).toHaveCount(left - 1)
  }
  await expect(page.getByTestId('machine-wide')).toBeVisible()
})

const SESSION_ID = '5e55a0a0-1111-4111-8111-111111111111'

// Claude Code keeps `<projects>/<folder with / as ->/<uuid>.jsonl`; some early row has the cwd.
function claudeSession(folder: string, id = SESSION_ID): void {
  const base = process.env[CLAUDE_DIR_ENV]
  if (!base)
    throw new Error(`${CLAUDE_DIR_ENV} is unset; run the specs through playwright.config.ts`)
  const directory = join(base, 'projects', folder.replaceAll('/', '-'))
  mkdirSync(directory, { recursive: true })
  const rows = [{ type: 'mode' }, { type: 'user', cwd: folder, message: 'hello' }]
  writeFileSync(join(directory, `${id}.jsonl`), rows.map((r) => JSON.stringify(r)).join('\n'))
}

async function reject(page: Page, ids: number[]): Promise<void> {
  // The approvals these steps created are decided, so later specs find the seed as it was.
  for (const id of ids) {
    const response = await page.request.post(`/api/approvals/${id}/decision`, {
      data: { decision: 'reject' },
      headers: { 'Idempotency-Key': `e2e-sessions-${id}`, 'X-Labhq-Request': '1' },
    })
    expect(response.ok()).toBe(true)
  }
}

test('the owner sees sessions per project, continues one, reads an analysis estimate', async ({
  signedInPage: page,
}) => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'labhq-sessions-')))
  const repo = join(root, 'party')
  repository(repo)
  claudeSession(repo)
  // A session in a folder outside the one the owner sets must never show.
  const stranger = realpathSync(mkdtempSync(join(tmpdir(), 'labhq-stranger-')))
  claudeSession(stranger, '5e55a0a0-2222-4222-8222-222222222222')

  await page.goto('/ceo')
  await page.getByTestId('root-path').fill(root)
  await page.getByTestId('add-button').click()
  await expect(page.getByTestId(`root-${root}`)).toBeVisible()

  // The Sessions sidebar item opens the full view, with the project's session and its action.
  await page.getByTestId('nav-item').filter({ hasText: 'Sessions' }).click()
  await expect(page).toHaveURL(/\/sessions$/)
  // The panel's own scan may still be running, and an earlier scan may be on record: ask again.
  await page.getByTestId('scan-now-sessions').click()
  const block = page.getByTestId('scanned-party')
  await expect(block).toBeVisible()
  await expect(block.getByTestId('session-row')).toContainText('claude-code')
  await expect(block.getByTestId('proposal')).toBeVisible()
  await expect(page.getByTestId('scanned-projects').getByTestId('session-row')).toHaveCount(1)
  await expect(page.getByTestId('last-scan')).toContainText('left out')
  await expect(page.getByText(stranger)).toHaveCount(0)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true)

  // Analyse shows its estimate before anything runs.
  await block.getByTestId('analyse').click()
  await expect(block.getByTestId('action-summary')).toContainText('Approve approval')
  const analysis = Number(
    /approval (\d+)/.exec(await block.getByTestId('approval-link').innerText())?.[1],
  )

  // Continue only records an approval.
  await block.getByTestId('continue').click()
  await expect(block.getByTestId('approval-link')).not.toContainText(`approval ${analysis}`)
  const resume = Number(
    /approval (\d+)/.exec(await block.getByTestId('approval-link').innerText())?.[1],
  )
  await reject(page, [analysis, resume])

  // Continuing registered the folder as a labhq project, so its card and page show the sessions.
  const listed = await page.request.get('/api/projects')
  const { items } = (await listed.json()) as { items: { id: number; name: string }[] }
  const id = items.find((item) => item.name === 'party')?.id
  expect(id).toBeDefined()
  await page.goto('/projects')
  await expect(page.getByTestId('session-counts')).toContainText('Sessions: 1 · 0 running · 1 idle')
  await page.goto(`/projects/${id}`)
  await expect(page.getByTestId('project-sessions')).toContainText('claude-code')

  // Leave the shared seed as found for the specs that run after this one.
  await page.goto('/ceo')
  await expect(page.getByTestId('roots')).toBeVisible()
  const removals = page.getByTestId('session-scan').getByRole('button', { name: 'Remove' })
  for (let left = await removals.count(); left > 0; left--) {
    await removals.first().click()
    await expect(removals).toHaveCount(left - 1)
  }
})
