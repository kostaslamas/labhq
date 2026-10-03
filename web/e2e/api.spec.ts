import { expect, test } from '@playwright/test'

import type { components } from '../src/api/schema'
import { seedSummary } from './support/server.ts'

type Health = components['schemas']['Health']

test('the harness serves a seeded labhq whose health check answers', async ({
  request,
  baseURL,
}) => {
  expect(baseURL).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)
  const response = await request.get('/api/health')
  expect(response.status()).toBe(200)
  const health = (await response.json()) as Health
  expect(health.version).toMatch(/^\d+\.\d+/)

  const seeded = seedSummary()
  expect(seeded.projects).toHaveLength(2)
  expect(seeded.runs.length).toBeGreaterThan(0)
  expect(Object.keys(seeded.approvals).sort()).toEqual(['heavy', 'light'])
})

test('protected routes answer with the error envelope without a session', async ({ request }) => {
  const response = await request.get('/api/vocabulary')
  expect(response.status()).toBe(401)
  const body = (await response.json()) as components['schemas']['ErrorEnvelope']
  expect(body.error.code).toBe('unauthorized')
})

test('the built UI is served by labhq itself', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/today$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Today')
})
