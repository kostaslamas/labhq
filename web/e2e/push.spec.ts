import { expect, test } from './support/auth.ts'

// Delivering a push needs the browser vendor's push service, which these specs never reach. They
// check what is ours: the installable shell, the worker, the page and the guarded API.

test('the app is installable: a standalone manifest and a worker served from the root', async ({
  request,
}) => {
  const manifest = await request.get('/manifest.webmanifest')
  expect(manifest.status()).toBe(200)
  const body = (await manifest.json()) as { display: string; start_url: string; icons: unknown[] }
  expect(body.display).toBe('standalone')
  expect(body.start_url).toBe('/')
  expect(body.icons.length).toBeGreaterThanOrEqual(2)

  const worker = await request.get('/sw.js')
  expect(worker.status()).toBe(200)
  expect(worker.headers()['content-type']).toContain('javascript')
})

test('subscribing without a passkey session is refused over HTTP', async ({ request }) => {
  const response = await request.post('/api/push/subscriptions', {
    headers: { 'X-Labhq-Request': '1' },
    data: { endpoint: 'https://push.example.test/send/x', keys: { p256dh: 'k', auth: 'a' } },
  })
  expect(response.status()).toBe(401)
})

test('the signed-in owner reaches the enable step and the worker registers', async ({
  signedInPage,
}) => {
  // Headless Chromium reports notifications as denied whatever the permission, which would hide
  // the step; the page under test sees the state of a browser that has not been asked yet.
  await signedInPage.evaluate(() =>
    Object.defineProperty(Notification, 'permission', { get: () => 'default' }),
  )
  await signedInPage.getByTestId('notifications-link').click()

  await expect(signedInPage.getByRole('heading', { level: 1 })).toHaveText('Notifications')
  await expect(signedInPage.getByTestId('enable-notifications')).toBeVisible()
  await expect(signedInPage.getByTestId('push-state')).toContainText('does not receive')
  // The e2e server runs with ntfy as its notifier, and the page says approvals go there.
  await expect(signedInPage.getByTestId('push-inactive')).toBeVisible()
  const scope = await signedInPage.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    return registration.scope
  })
  expect(new URL(scope).pathname).toBe('/')
})
