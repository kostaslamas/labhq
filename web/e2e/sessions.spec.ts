import { tmpdir } from 'node:os'

import { expect, test } from './support/auth.ts'

// A folder that exists on the machine running the seeded server, and is not `/` or home.
const FOLDER = tmpdir()

test('the owner adds and removes a scan folder with a passkey, and it is stored', async ({
  signedInPage: page,
}) => {
  await page.goto('/session-scan')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Session scan')
  await expect(page.getByTestId('machine-wide')).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true)

  await page.getByTestId('root-path').fill(FOLDER)
  await page.getByTestId('add-button').click()
  await expect(page.getByTestId('roots')).toContainText(FOLDER.split('/').pop() ?? FOLDER)
  const stored = await page.request.get('/api/session-scan')
  expect(((await stored.json()) as { machine_wide: boolean }).machine_wide).toBe(false)

  // Survives a reload, so it was stored and not only drawn.
  await page.reload()
  await expect(page.getByTestId('roots')).toBeVisible()

  // Leave the shared seed as found for the specs that run after this one.
  await page.getByTestId('roots').getByRole('button').click()
  await expect(page.getByTestId('machine-wide')).toBeVisible()
})

test('a refused folder shows the reason and changes nothing', async ({ signedInPage: page }) => {
  await page.goto('/session-scan')
  await page.getByTestId('root-path').fill('/')
  await page.getByTestId('add-button').click()

  await expect(page.getByTestId('sessions-failure')).toContainText('root of a filesystem')
  await expect(page.getByTestId('machine-wide')).toBeVisible()
})
