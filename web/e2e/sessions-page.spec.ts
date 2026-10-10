import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import type { Page } from '@playwright/test'

import { expect, test } from './support/auth.ts'
import { CLAUDE_DIR_ENV } from './support/server.ts'

const SESSION_ID = '5e55a0a0-1111-4111-8111-111111111111'

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

  await page.goto('/projects')
  await page.getByTestId('root-path').fill(root)
  await page.getByTestId('add-button').click()
  await expect(page.getByTestId(`root-${root}`)).toBeVisible()

  // The fifth sidebar item opens the full view, with the project's session and its action.
  await page.getByTestId('nav-item').filter({ hasText: 'Sessions' }).click()
  await expect(page).toHaveURL(/\/sessions$/)
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
  await page.goto('/projects')
  await expect(page.getByTestId('roots')).toBeVisible()
  const removals = page.getByTestId('session-scan').getByRole('button', { name: 'Remove' })
  for (let left = await removals.count(); left > 0; left--) {
    await removals.first().click()
    await expect(removals).toHaveCount(left - 1)
  }
})
