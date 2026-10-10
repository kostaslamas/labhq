import type { Page } from '@playwright/test'

import { expect, test } from './support/auth.ts'

const areas = [
  { path: '/today', en: 'Today', el: 'Σήμερα' },
  { path: '/projects', en: 'Projects', el: 'Έργα' },
  { path: '/meetings', en: 'Meetings', el: 'Συσκέψεις' },
  { path: '/approvals', en: 'Approvals', el: 'Εγκρίσεις' },
]

async function hasNoHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
}

test('each sidebar item opens its area without horizontal scroll', async ({
  signedInPage: page,
}) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/today$/)
  const items = page.getByTestId('nav-item')
  await expect(items).toHaveText(areas.map((area) => area.en))

  for (const area of areas) {
    await items.filter({ hasText: area.en }).click()
    await expect(page).toHaveURL(new RegExp(`${area.path}$`))
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(area.en)
    expect(await hasNoHorizontalScroll(page)).toBe(true)
  }
})

test('switching language changes the shell strings', async ({ signedInPage: page }) => {
  await page.goto('/today')
  await page.getByTestId('switch-language').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'el')
  await expect(page.getByTestId('nav-item')).toHaveText(areas.map((area) => area.el))
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Σήμερα')

  await page.reload()
  await expect(page.getByTestId('nav-item').first()).toHaveText('Σήμερα')
})

test('the built app requests nothing outside its own origin and uses bundled fonts', async ({
  signedInPage: page,
  baseURL,
}) => {
  const requests: string[] = []
  page.on('request', (request) => requests.push(request.url()))
  await page.goto('/today')
  await page.evaluate(() => document.fonts.ready)

  const origin = new URL(baseURL ?? '').origin
  expect(requests.filter((url) => !url.startsWith(origin) && !url.startsWith('data:'))).toEqual([])
  const fonts = await page.evaluate(() =>
    [...document.fonts].filter((font) => font.status === 'loaded').map((font) => font.family),
  )
  expect(fonts.map((family) => family.replace(/"/g, ''))).toContain('Oxanium')
})
