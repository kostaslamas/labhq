import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import type { components } from '../src/api/schema'
import { expect, test } from './support/auth.ts'
import { DATA_DIR_ENV, seedSummary } from './support/server.ts'

type Approval = components['schemas']['ApprovalOut']

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

// Another process of the same labhq: it shares the database, not the server's memory.
function labhq(args: string[], script?: string): string {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir) throw new Error(`${DATA_DIR_ENV} is unset; run the specs through playwright`)
  const command = script
    ? ['run', '--frozen', 'python', '-c', script]
    : ['run', '--frozen', 'labhq', ...args]
  const result = spawnSync('uv', command, {
    cwd: repoRoot,
    encoding: 'utf-8',
    env: { ...process.env, LABHQ_DATA_DIR: dataDir },
  })
  if (result.status !== 0) throw new Error(`${command.join(' ')} failed:\n${result.stderr}`)
  return result.stdout.trim()
}

const REQUEST_LIGHT = `
import asyncio
from labhq.approvals import ApprovalService
from labhq.cli.context import execute

async def body(context):
    approval = await ApprovalService(context.sessions, clock=context.clock).request(
        "start_meeting", {"topic": "e2e"}
    )
    print(approval.id)

execute(body)
`

function requestLightApproval(): number {
  return Number(labhq([], REQUEST_LIGHT).split('\n').at(-1))
}

async function stored(page: import('@playwright/test').Page, id: number): Promise<Approval> {
  const response = await page.request.get(`/api/approvals/${id}`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as Approval
}

test('a light approval resolves with one tap and records it', async ({ signedInPage: page }) => {
  const id = requestLightApproval()
  await page.goto('/approvals')
  await page.getByTestId(`approval-${id}`).click()

  await page.getByTestId('approve').click()

  await expect(page.getByTestId('decision')).toBeVisible()
  await expect(page.getByTestId('decided-how')).toHaveText('a tap')
  await expect(page.getByTestId('approval-actions')).toHaveCount(0)
  const row = await stored(page, id)
  expect(row.confirmation_kind).toBe('tap')
  expect(row.decided_by).toBe('web:owner')
  expect(row.decided_at).not.toBeNull()
})

test('a heavy approval needs a passkey: a dismissed prompt leaves it pending, then it resolves', async ({
  signedInPage: page,
  authenticator,
}) => {
  const id = seedSummary().approvals.heavy
  await page.goto('/approvals')
  await page.getByTestId(`approval-${id}`).click()

  // No assertion at all: the API refuses and nothing is decided.
  const bare = await page.request.post(`/api/approvals/${id}/decision`, {
    data: { decision: 'approve' },
    headers: { 'Idempotency-Key': 'e2e-bare', 'X-Labhq-Request': '1' },
  })
  expect(bare.status()).toBe(403)

  // A device that cannot verify the user: the prompt fails, the approval stays pending.
  await authenticator.session.send('WebAuthn.setUserVerified', {
    authenticatorId: authenticator.id,
    isUserVerified: false,
  })
  await page.getByTestId('approve').click()
  await expect(page.getByTestId('decision-error')).toContainText('still pending')
  expect((await stored(page, id)).status).toBe('pending')

  await authenticator.session.send('WebAuthn.setUserVerified', {
    authenticatorId: authenticator.id,
    isUserVerified: true,
  })
  await page.getByTestId('approve').click()

  await expect(page.getByTestId('decision')).toBeVisible()
  await expect(page.getByTestId('decided-how')).toHaveText('a passkey')
  const row = await stored(page, id)
  expect(row.confirmation_kind).toBe('passkey')
  expect(row.status).not.toBe('pending')
})

test('an approval created by another process appears without a refresh', async ({
  signedInPage: page,
}) => {
  await page.goto('/approvals')
  await expect(page.getByTestId('approval-list')).toBeVisible()

  const id = requestLightApproval()

  await expect(page.getByTestId(`approval-${id}`)).toBeVisible({ timeout: 3000 })
})

test('an approval settled elsewhere shows who decided and offers no action', async ({
  signedInPage: page,
}) => {
  const id = requestLightApproval()
  await page.goto('/approvals')
  await page.getByTestId(`approval-${id}`).click()
  await expect(page.getByTestId('approve')).toBeVisible()

  labhq(['approvals', 'approve', String(id)])

  await expect(page.getByTestId('decided-how')).toHaveText('the command line', { timeout: 5000 })
  await expect(page.getByTestId('decided-by')).toContainText('cli:')
  await expect(page.getByTestId('approve')).toHaveCount(0)
  await expect(page.getByTestId('reject')).toHaveCount(0)
})

test('the page does not scroll sideways at 1280x800', async ({ signedInPage: page }) => {
  await page.goto('/approvals')
  await expect(page.getByTestId('approval-list')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
