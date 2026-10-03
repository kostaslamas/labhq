import type { components } from '../src/api/schema'
import { enrollmentLink, enrollThroughUi, expect, signInThroughUi, test } from './support/auth.ts'

type ErrorEnvelope = components['schemas']['ErrorEnvelope']

test('without a session every protected API route is 401 and the UI shows the login page', async ({
  page,
  request,
}) => {
  const response = await request.get('/api/vocabulary')
  expect(response.status()).toBe(401)
  expect(((await response.json()) as ErrorEnvelope).error.code).toBe('unauthorized')

  await page.goto('/today')
  await expect(page).toHaveURL(/\/login\?next=\/today$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in to labhq')
  await expect(page.locator('aside')).toHaveCount(0)
})

test('enrolling through the CLI link, signing in and signing out', async ({
  page,
  request,
  baseURL,
}) => {
  await enrollThroughUi(page, enrollmentLink(baseURL ?? ''), 'e2e laptop')
  await page.getByTestId('go-sign-in').click()
  await signInThroughUi(page)

  await expect(page).toHaveURL(/\/today$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Today')
  // The session cookie authenticates the page's own API calls, not other clients.
  expect((await page.request.get('/api/vocabulary')).status()).toBe(200)
  expect((await request.get('/api/vocabulary')).status()).toBe(401)

  await page.reload()
  await expect(page).toHaveURL(/\/today$/)

  await page.getByTestId('passkeys-link').click()
  await expect(page.getByTestId('passkey-list')).toContainText('e2e laptop')
  await page.getByTestId('sign-out').click()
  await expect(page).toHaveURL(/\/login$/)
  expect((await page.request.get('/api/vocabulary')).status()).toBe(401)
})

test('an enrollment link works once', async ({ page, baseURL }) => {
  const link = enrollmentLink(baseURL ?? '')
  await enrollThroughUi(page, link, 'first use')

  // A different document, so the page reads the link afresh instead of keeping its state.
  await page.goto('/login')
  await page.goto(link)
  await page.getByTestId('create-passkey').click()
  await expect(page.getByTestId('enroll-error')).toContainText('already used')
})

test('a signed-in owner can show a link and QR code for another device', async ({
  signedInPage,
}) => {
  await signedInPage.getByTestId('passkeys-link').click()
  await signedInPage.getByTestId('add-passkey').click()
  const link = signedInPage.getByTestId('enrollment-link')
  await expect(link.getByRole('img')).toBeVisible()
  await expect(link).toContainText('/enroll#')
})
