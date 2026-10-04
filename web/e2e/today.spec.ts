import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { DATA_DIR_ENV, seedSummary } from './support/server.ts'
import { expect, test } from './support/auth.ts'

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

// Writes through the engine's own models into the seeded database, from another process: the
// live feed has to notice it the way it notices the scheduler's writes.
const WRITE = String.raw`
import asyncio, json, sys
from datetime import UTC, datetime
from labhq.db import create_engine, session_factory
from sqlalchemy import select
from labhq.db.enums import ApprovalStatus, IncidentStatus, RiskClass, TaskStatus
from labhq.db.models import Approval, HealthRule, Host, Incident, Task
from labhq.settings import Settings

action, data_dir, task_id = sys.argv[1], sys.argv[2], int(sys.argv[3])

async def main():
    settings = Settings(data_dir=data_dir, database_url=None)
    engine = create_engine(settings.resolved_database_url)
    now = datetime.now(UTC)
    async with session_factory(engine)() as db:
        if action == "deliver":
            task = await db.get(Task, task_id)
            task.status, task.updated_at = TaskStatus.DONE, now
            db.add(Approval(type="push", risk_class=RiskClass.HEAVY, status=ApprovalStatus.EXECUTED,
                payload={"branch": "labhq/task-%d-readme" % task_id, "commit": "b" * 40},
                task_id=task_id, executed_at=now, created_at=now))
        elif action == "ask":
            approval = Approval(type="assign_task", risk_class=RiskClass.LIGHT, payload={}, created_at=now)
            db.add(approval)
            await db.flush()
            print(approval.id)
        elif action == "incident":
            # The server's collector resolves incidents of enabled rules the host does not
            # violate, so the seeded one may be gone on a CI machine. Own one that a disabled
            # rule keeps open, and close the rest so the page is the same everywhere.
            for open_one in await db.scalars(select(Incident).where(Incident.status == IncidentStatus.OPEN)):
                open_one.status, open_one.resolved_at = IncidentStatus.RESOLVED, now
            host = Host(name="spec-host", created_at=now, updated_at=now)
            db.add(host)
            await db.flush()
            rule = HealthRule(type="threshold", name="Spec rule", params={}, host_id=host.id,
                reason="Seeded by the Today spec.", created_by="e2e", enabled=False,
                created_at=now, updated_at=now)
            db.add(rule)
            await db.flush()
            incident = Incident(rule_id=rule.id, host_id=host.id, opened_at=now)
            db.add(incident)
            await db.flush()
            print(incident.id)
        elif action == "resolve":
            incident = await db.get(Incident, task_id)
            incident.status, incident.resolved_at = IncidentStatus.RESOLVED, now
        else:
            approval = await db.get(Approval, task_id)
            approval.status = ApprovalStatus.CANCELLED
        await db.commit()
    await engine.dispose()

asyncio.run(main())
`

function write(action: 'deliver' | 'ask' | 'cancel' | 'incident' | 'resolve', id: number): string {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir) throw new Error(`${DATA_DIR_ENV} is unset`)
  const result = spawnSync(
    'uv',
    ['run', '--frozen', 'python', '-c', WRITE, action, dataDir, String(id)],
    { cwd: repoRoot, encoding: 'utf-8' },
  )
  if (result.status !== 0) throw new Error(`write ${action} failed:\n${result.stderr}`)
  return result.stdout.trim()
}

test.describe.configure({ mode: 'serial' })

let incident = 0
test.afterAll(() => {
  if (incident) write('resolve', incident)
})

test('Today shows what was delivered and what needs you, never agents at work', async ({
  signedInPage: page,
}) => {
  // The second seeded task has no run; delivering it leaves the first task's spend without output.
  write('deliver', seedSummary().tasks[1]!)
  incident = Number(write('incident', 0))
  await page.goto('/today')

  await expect(page.getByTestId('deliverable')).toHaveCount(1)
  await expect(page.getByTestId('deliverable')).toContainText('Write the README')
  await expect(page.getByTestId('deliverable')).toContainText('labhq/task-')
  await expect(page.getByTestId('need-approval')).toHaveCount(2)
  await expect(page.getByTestId('need-question')).toHaveCount(1)
  await expect(page.getByTestId('need-incident')).toHaveCount(1)
  await expect(page.getByTestId('spend-warning')).toHaveCount(1)

  // Results, not activity (plan §8.2.1): no running-agent list and no "working" label.
  const body = page.locator('main')
  await expect(body).not.toContainText(/working/i)
  await expect(body).not.toContainText(/agents? (at work|running)/i)
  await expect(page.locator('[data-state="working"]')).toHaveCount(0)

  await expect(page).toHaveScreenshot('today.png', {
    fullPage: true,
    mask: [page.locator('time')],
    maxDiffPixelRatio: 0.02,
  })
})

test('spend without a deliverable is a warning with its amount', async ({ signedInPage: page }) => {
  await page.goto('/today')
  const warning = page.getByTestId('spend-warning')
  await expect(warning).toHaveCount(1)
  await expect(warning).toContainText('delivered nothing')
  await expect(warning.locator('[data-mono]')).toHaveText(/^\$\d[\d,]*\.\d{2,6}$/)
})

test('a new pending approval raises the needs-you count without a refresh', async ({
  signedInPage: page,
}) => {
  await page.goto('/today')
  const count = page.getByTestId('needs-count')
  await expect(count).toHaveText('4')

  const approval = Number(write('ask', 0))
  try {
    await expect(count).toHaveText('5')
    await expect(page.getByTestId('need-approval')).toHaveCount(3)
  } finally {
    write('cancel', approval)
  }
  await expect(count).toHaveText('4')
})

test('the page does not scroll sideways at 1280 by 800', async ({ signedInPage: page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/today')
  await expect(page.getByTestId('deliverable')).toHaveCount(1)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
