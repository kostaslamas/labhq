import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import type { Page } from '@playwright/test'

import { expect, test } from './support/auth.ts'
import { DATA_DIR_ENV, seedSummary } from './support/server.ts'

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

const BULK_PROJECTS = 20
// The names sort after the seeded projects, so the grid shows them in a known order.
const WARN = 'zz-e2e-warn'
const STOP = 'zz-e2e-stop'
const DEEP = 'zz-e2e-deep'
const bulkName = (index: number) => `zz-e2e-bulk-${String(index).padStart(2, '0')}`

// Adds rows through the engine's own services, in the seeded database the server reads.
// A project at 80% and one at 100% of a $1 budget, 20 empty ones, and one with a four-level
// team whose titles name their depth.
const SEED_SCRIPT = `
import asyncio, json, sys
from pathlib import Path
from labhq.cli.context import Context
from labhq.cli.work import create_agent, create_project
from labhq.clock import SystemClock
from labhq.db import create_engine, session_factory
from labhq.db.enums import AgentStatus
from labhq.db.models import CostEvent
from labhq.settings import Settings

BULK, WARN, STOP, DEEP = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
MICROS = 1_000_000

async def main():
    settings = Settings(data_dir=Path(sys.argv[5]), database_url=None)
    engine = create_engine(settings.resolved_database_url)
    context = Context(settings, session_factory(engine), SystemClock())
    repo = Path(sys.argv[6])
    spent = {}
    for name, used in ((WARN, 800_000), (STOP, 1_000_000)):
        project = await create_project(context, name, repo, MICROS)
        agent = await create_agent(context, project=name, role='worker', title='Spender',
                                   adapter='fake', status=AgentStatus.ACTIVE)
        spent[name] = (project.id, agent.id, used)
    for index in range(BULK):
        await create_project(context, f'zz-e2e-bulk-{index:02d}', repo, None)
    deep = await create_project(context, DEEP, repo, 5 * MICROS)
    parent = None
    for level, role in enumerate(('ceo', 'manager', 'lead', 'worker'), start=1):
        agent = await create_agent(context, project=DEEP, role=role, title=f'Level {level} {role}',
                                   adapter='fake', reports_to=parent, status=AgentStatus.ACTIVE)
        parent = agent.id
    async with context.sessions() as db:
        for project_id, agent_id, used in spent.values():
            db.add(CostEvent(agent_id=agent_id, project_id=project_id, cost_micros=used,
                             created_at=context.clock.now()))
        await db.commit()
    await engine.dispose()

asyncio.run(main())
`

test.describe.configure({ mode: 'serial' })

test.beforeAll(() => {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir) throw new Error(`${DATA_DIR_ENV} is unset; run the specs through playwright.config`)
  const result = spawnSync(
    'uv',
    [
      'run',
      '--frozen',
      'python',
      '-c',
      SEED_SCRIPT,
      String(BULK_PROJECTS),
      WARN,
      STOP,
      DEEP,
      dataDir,
      // Projects only store the path; nothing reads the repository here.
      repoRoot,
    ],
    { cwd: repoRoot, encoding: 'utf-8' },
  )
  if (result.status !== 0) throw new Error(`seeding projects failed:\n${result.stderr}`)
})

async function hasNoHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
}

function card(page: Page, name: string) {
  return page
    .getByTestId('project-grid')
    .locator('> li')
    .filter({ has: page.getByRole('link', { name, exact: true }) })
}

test('every project has a card with budget used and limit, and the warning matches 80% and 100%', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects')
  const cards = page.getByTestId('project-grid').locator('> li')
  // The two seeded projects, the budgeted pair, the bulk ones and the deep one.
  await expect(cards.first()).toBeVisible()
  expect(await cards.count()).toBeGreaterThanOrEqual(2 + 2 + BULK_PROJECTS + 1)

  const warn = card(page, WARN)
  await expect(warn.getByTestId('budget-spent')).toHaveText('$0.80')
  await expect(warn.getByTestId('budget-limit')).toHaveText('$1.00')
  await expect(warn.locator('[data-budget-state]')).toHaveAttribute('data-budget-state', 'warn')
  await expect(warn.getByTestId('budget-warning')).toBeVisible()

  const stop = card(page, STOP)
  await expect(stop.getByTestId('budget-spent')).toHaveText('$1.00')
  await expect(stop.locator('[data-budget-state]')).toHaveAttribute('data-budget-state', 'stop')

  const quiet = card(page, bulkName(0))
  await expect(quiet.locator('[data-budget-state]')).toHaveAttribute('data-budget-state', 'allow')
  await expect(quiet.getByTestId('budget-warning')).toHaveCount(0)
  // Seeded projects carry their latest deliverable or say nothing was delivered.
  await expect(quiet.getByTestId('latest-deliverable')).toContainText('Nothing delivered yet.')
})

test('budget and cost render in mono', async ({ signedInPage: page }) => {
  await page.goto('/projects')
  const spent = card(page, WARN).getByTestId('budget-spent')
  await expect(spent).toHaveAttribute('data-mono', '')
  const family = await spent.evaluate((node) => getComputedStyle(node).fontFamily)
  expect(family).toContain('Plex Mono')
})

test('the team tree expands and collapses to the full depth of reports_to', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects')
  await card(page, DEEP).getByTestId('project-link').click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(DEEP)

  const titles = page.getByTestId('team-title')
  await expect(titles).toHaveText(['Level 1 ceo', 'Level 2 manager'])

  await page.getByRole('button', { name: 'Show who reports to Level 2 manager' }).click()
  await expect(titles).toHaveText(['Level 1 ceo', 'Level 2 manager', 'Level 3 lead'])
  await page.getByRole('button', { name: 'Show who reports to Level 3 lead' }).click()
  await expect(titles).toHaveText([
    'Level 1 ceo',
    'Level 2 manager',
    'Level 3 lead',
    'Level 4 worker',
  ])
  expect(await hasNoHorizontalScroll(page)).toBe(true)

  await page.getByTestId('collapse-all').click()
  await expect(titles).toHaveText(['Level 1 ceo'])
  await page.getByTestId('expand-all').click()
  await expect(titles).toHaveCount(4)
})

test('there is no horizontal scroll at 1280x800 with 20 projects and a four-level team', async ({
  signedInPage: page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/projects')
  await expect(page.getByTestId('project-grid').locator('> li').first()).toBeVisible()
  expect(await page.getByTestId('project-grid').locator('> li').count()).toBeGreaterThanOrEqual(25)
  expect(await hasNoHorizontalScroll(page)).toBe(true)

  await card(page, DEEP).getByTestId('project-link').click()
  await page.getByTestId('expand-all').click()
  await expect(page.getByTestId('team-title')).toHaveCount(4)
  expect(await hasNoHorizontalScroll(page)).toBe(true)
})

test('the seeded project shows its team', async ({ signedInPage: page }) => {
  await page.goto('/projects')
  await card(page, 'atlas').getByTestId('project-link').click()
  await expect(page.getByTestId('team-title').first()).toHaveText('Project manager')
  await expect(page.getByTestId('team-tree')).toContainText('fake')
})

test('a task link opens the project that owns the task', async ({ signedInPage: page }) => {
  await page.goto(`/projects?task=${seedSummary().tasks[0]}`)
  await expect(page).toHaveURL(/\/projects\/\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('atlas')
})
