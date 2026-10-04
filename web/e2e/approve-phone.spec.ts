import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import type { Page } from '@playwright/test'

import type { components } from '../src/api/schema'
import { enrollThroughUi, enrollmentLink, expect, localhostOrigin, test } from './support/auth.ts'
import { DATA_DIR_ENV } from './support/server.ts'

type Approval = components['schemas']['ApprovalOut']

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

// An iPhone-class screen with touch input: the notification link opens on this.
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

const REQUEST = `
import asyncio
from labhq.approvals import ApprovalService
from labhq.cli.context import execute

async def body(context):
    approval = await ApprovalService(context.sessions, clock=context.clock).request(
        ACTION, PAYLOAD
    )
    print(approval.id)

execute(body)
`

const HEAVY = ['delete_branch', '{"members": ["a"], "lead": "m"}'] as const
const LIGHT = ['start_meeting', '{"topic": "e2e"}'] as const

// A new approval from another process, as an agent would raise it.
function requestApproval([action, payload]: readonly [string, string]): number {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir) throw new Error(`${DATA_DIR_ENV} is unset; run the specs through playwright`)
  const script = REQUEST.replace('ACTION', JSON.stringify(action)).replace('PAYLOAD', payload)
  const result = spawnSync('uv', ['run', '--frozen', 'python', '-c', script], {
    cwd: repoRoot,
    encoding: 'utf-8',
    env: { ...process.env, LABHQ_DATA_DIR: dataDir },
  })
  if (result.status !== 0) throw new Error(`request failed:\n${result.stderr}`)
  return Number(result.stdout.trim().split('\n').at(-1))
}

async function stored(page: Page, id: number): Promise<Approval> {
  const response = await page.request.get(`/api/approvals/${id}`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as Approval
}

// The phone has a passkey for this host but no session, as after tapping a notification.
async function enrolledPhone(page: Page, baseURL: string | undefined): Promise<void> {
  await enrollThroughUi(page, enrollmentLink(localhostOrigin(baseURL)), 'phone')
}

async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
}

test('the link signs in with the passkey, shows the action and resolves a heavy approval', async ({
  page,
  baseURL,
}) => {
  const id = requestApproval(HEAVY)
  await enrolledPhone(page, baseURL)

  await page.goto(`/approve/${id}`)
  // Nothing about the approval is shown before the first passkey prompt.
  await expect(page.getByTestId('approval-detail')).toHaveCount(0)
  await page.getByTestId('sign-in').click()

  await expect(page.getByTestId('approval-detail')).toBeVisible()
  await expect(page.getByTestId('approval-payload')).toContainText('"lead"')
  // Bare layout: no sidebar around the page.
  await expect(page.getByRole('navigation')).toHaveCount(0)

  await page.getByTestId('approve').click()

  await expect(page.getByTestId('decided-how')).toHaveText('a passkey')
  await expect(page.getByTestId('approve')).toHaveCount(0)
  const row = await stored(page, id)
  expect(row.confirmation_kind).toBe('passkey')
  expect(row.status).not.toBe('pending')
})

test('without a successful passkey the heavy approval stays pending', async ({
  page,
  baseURL,
  authenticator,
}) => {
  const id = requestApproval(HEAVY)
  await enrolledPhone(page, baseURL)
  await page.goto(`/approve/${id}`)
  await page.getByTestId('sign-in').click()
  await expect(page.getByTestId('approve')).toBeVisible()

  // The device cannot verify the person: the second prompt fails.
  await authenticator.session.send('WebAuthn.setUserVerified', {
    authenticatorId: authenticator.id,
    isUserVerified: false,
  })
  await page.getByTestId('approve').click()

  await expect(page.getByTestId('decision-error')).toContainText('still pending')
  expect((await stored(page, id)).status).toBe('pending')

  // The session alone never decides it either.
  const bare = await page.request.post(`/api/approvals/${id}/decision`, {
    data: { decision: 'approve' },
    headers: { 'Idempotency-Key': 'e2e-phone-bare', 'X-Labhq-Request': '1' },
  })
  expect(bare.status()).toBe(403)
  expect((await stored(page, id)).status).toBe('pending')
})

test('a failed first prompt reveals nothing', async ({ page, baseURL, authenticator }) => {
  const id = requestApproval(HEAVY)
  await enrolledPhone(page, baseURL)
  await authenticator.session.send('WebAuthn.setUserVerified', {
    authenticatorId: authenticator.id,
    isUserVerified: false,
  })

  await page.goto(`/approve/${id}`)
  await page.getByTestId('sign-in').click()

  await expect(page.getByTestId('login-error')).toBeVisible()
  await expect(page.getByTestId('approval-detail')).toHaveCount(0)
})

test('the page fits a 390x844 phone and every control is at least 44 px tall', async ({
  page,
  baseURL,
}) => {
  const id = requestApproval(HEAVY)
  await enrolledPhone(page, baseURL)
  await page.goto(`/approve/${id}`)

  expect(await overflow(page)).toBeLessThanOrEqual(0)
  const signIn = await page.getByTestId('sign-in').boundingBox()
  expect(signIn?.height).toBeGreaterThanOrEqual(44)

  await page.getByTestId('sign-in').click()
  await expect(page.getByTestId('approve')).toBeVisible()

  expect(await overflow(page)).toBeLessThanOrEqual(0)
  for (const testId of ['approve', 'reject']) {
    const box = await page.getByTestId(testId).boundingBox()
    expect(box?.height).toBeGreaterThanOrEqual(44)
    expect(box?.width).toBeGreaterThanOrEqual(44)
  }
})

test('a decided approval shows its state and nothing to press', async ({ page, baseURL }) => {
  const id = requestApproval(LIGHT)
  await enrolledPhone(page, baseURL)
  await page.goto(`/approve/${id}`)
  await page.getByTestId('sign-in').click()
  await page.getByTestId('approve').click()
  await expect(page.getByTestId('decision')).toBeVisible()

  await page.reload()

  await expect(page.getByTestId('decision')).toBeVisible()
  await expect(page.getByTestId('approve')).toHaveCount(0)
  await expect(page.getByTestId('reject')).toHaveCount(0)
})

test('an unknown approval says so and offers nothing to press', async ({ page, baseURL }) => {
  await enrolledPhone(page, baseURL)
  await page.goto('/approve/999999')
  await page.getByTestId('sign-in').click()

  await expect(page.getByTestId('approve-unknown')).toBeVisible()
  await expect(page.getByTestId('approve')).toHaveCount(0)
})
