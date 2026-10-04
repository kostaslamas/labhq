import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import type { Page } from '@playwright/test'

import { expect, test } from './support/auth.ts'
import { DATA_DIR_ENV, seedSummary } from './support/server.ts'

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

// What a CLI or a chat bridge in another process does: write an owner entry through the
// engine's own function, straight into the shared database.
const WRITE_ENTRY = `
import asyncio, sys
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory
from labhq.meetings import add_owner_entry
from labhq.settings import Settings

async def main(data_dir, meeting_id, text):
    settings = Settings(data_dir=data_dir, database_url=None)
    engine = create_engine(settings.resolved_database_url)
    try:
        await add_owner_entry(session_factory(engine), SystemClock(), meeting_id=int(meeting_id), text=text)
    finally:
        await engine.dispose()

asyncio.run(main(*sys.argv[1:]))
`

function writeFromAnotherProcess(meetingId: number, text: string): void {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir)
    throw new Error(`${DATA_DIR_ENV} is unset; run the specs through playwright.config.ts`)
  const result = spawnSync(
    'uv',
    ['run', '--frozen', 'python', '-c', WRITE_ENTRY, dataDir, String(meetingId), text],
    { cwd: repoRoot, encoding: 'utf-8' },
  )
  if (result.status !== 0) throw new Error(`writing the entry failed:\n${result.stderr}`)
}

async function hasNoHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
}

test('a seeded standup shows its agenda, conversation, and the minutes link to their tasks', async ({
  signedInPage: page,
}) => {
  const { standup, planning } = seedSummary().meetings

  await page.goto('/meetings')
  await expect(page.getByTestId('meeting-row')).toHaveCount(2)
  await page.getByTestId('meeting-row').filter({ hasText: 'standup' }).click()

  await expect(page).toHaveURL(new RegExp(`/meetings/${standup}$`))
  await expect(page.getByTestId('agenda')).toContainText('What is blocked, and what ships today?')
  await expect(page.getByTestId('participants').locator('li')).toHaveText([
    'Project manager',
    'Worker',
  ])
  await expect(page.getByTestId('speaker').nth(0)).toHaveText('Worker')
  await expect(page.getByTestId('speaker').nth(1)).toHaveText('Project manager')
  await expect(page.getByTestId('avatar').first()).toHaveText('W')
  // Long unbroken text wraps instead of scrolling the page sideways.
  expect(await hasNoHorizontalScroll(page)).toBe(true)

  await page.goto(`/meetings/${planning}`)
  await expect(page.getByTestId('decisions')).toContainText('Greet in Greek too')
  const item = page.getByTestId('action-items').locator('li')
  await expect(item).toContainText('Add a HELLO file')
  await item.getByRole('link').click()
  await expect(page).toHaveURL(/\/projects\/\d+$/)
})

test('an entry written by another process appears without a refresh', async ({
  signedInPage: page,
}) => {
  const { standup } = seedSummary().meetings
  await page.goto(`/meetings/${standup}`)
  await expect(page.getByTestId('message').first()).toBeVisible()
  const before = await page.getByTestId('message').count()

  writeFromAnotherProcess(standup, 'Written elsewhere, shown live.')
  await expect(page.getByTestId('message')).toHaveCount(before + 1)

  await expect(page.getByTestId('message-text').last()).toHaveText('Written elsewhere, shown live.')
})

test('joining posts the owner message into the transcript', async ({ signedInPage: page }) => {
  const { standup } = seedSummary().meetings
  await page.goto(`/meetings/${standup}`)

  await page.getByTestId('join-text').fill('Prioritise the login bug.')
  await page.getByTestId('join-send').click()

  const last = page.getByTestId('message').last()
  await expect(last).toHaveAttribute('data-source', 'owner')
  await expect(last.getByTestId('message-text')).toHaveText('Prioritise the login bug.')
  await expect(page.getByTestId('join-text')).toHaveValue('')

  await page.reload()
  await expect(
    page.getByTestId('message-text').filter({ hasText: 'Prioritise the login bug.' }),
  ).toHaveCount(1)
})

test('an ended meeting takes no message, and Greek strings are present', async ({
  signedInPage: page,
}) => {
  const { planning } = seedSummary().meetings
  await page.goto(`/meetings/${planning}`)
  await expect(page.getByTestId('join')).toHaveCount(0)

  await page.getByTestId('switch-language').click()
  await expect(page.getByRole('heading', { level: 2, name: 'Αποφάσεις' })).toBeVisible()
  expect(await hasNoHorizontalScroll(page)).toBe(true)
})
