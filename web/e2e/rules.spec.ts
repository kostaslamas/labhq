import type { Page } from '@playwright/test'

import type { components } from '../src/api/schema'
import { expect, test } from './support/auth.ts'

type Rule = components['schemas']['HealthRuleItem']

async function rules(page: Page): Promise<Rule[]> {
  const response = await page.request.get('/api/health/rules')
  expect(response.status()).toBe(200)
  return (await response.json()) as Rule[]
}

test('a rule an agent added shows its reason and creator and is disabled from the UI', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects/infra/rules')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Health rules')

  const [seeded] = await rules(page)
  if (!seeded) throw new Error('the seed has no health rule')
  const card = page.getByTestId(`rule-${seeded.id}`)
  await expect(card.getByTestId('rule-reason')).toHaveText(seeded.reason)
  await expect(card.getByTestId('rule-creator')).toContainText(seeded.created_by)
  await expect(card).toHaveAttribute('data-enabled', 'true')
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true)

  await card.getByTestId(`toggle-${seeded.id}`).click()
  await expect(card.getByTestId('rule-disabled')).toBeVisible()
  expect((await rules(page)).find((rule) => rule.id === seeded.id)?.enabled).toBe(false)

  // Survives a reload, so it was stored and not only drawn.
  await page.reload()
  await expect(page.getByTestId(`rule-${seeded.id}`)).toHaveAttribute('data-enabled', 'false')

  // Leave the shared seed as found for the specs that run after this one.
  await page.getByTestId(`toggle-${seeded.id}`).click()
  await expect(page.getByTestId(`rule-${seeded.id}`)).toHaveAttribute('data-enabled', 'true')
})

test('the page speaks Greek and the sidebar still has all areas', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects/infra/rules')
  await expect(page.getByTestId('nav-item')).toHaveCount(5)
  await page.getByTestId('switch-language').click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Κανόνες υγείας')
})
