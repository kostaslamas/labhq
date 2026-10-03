// Passkey support for end-to-end specs: a Chromium virtual authenticator, the one-time link
// from `labhq passkey enroll`, and a `signedInPage` fixture built from both.
//
// A passkey needs a domain as its relying-party id, and `127.0.0.1` is not one, so specs
// that use this `test` run on `http://localhost:<port>` (the server's own loopback address).
// The authenticator is internal, user-verifying and approves every prompt on its own.

import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, test as base, type CDPSession, type Page } from '@playwright/test'

import { DATA_DIR_ENV } from './server.ts'

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))

export function localhostOrigin(baseURL: string | undefined): string {
  const url = new URL(baseURL ?? '')
  url.hostname = 'localhost'
  return url.origin
}

export interface VirtualAuthenticator {
  session: CDPSession
  id: string
}

export async function addVirtualAuthenticator(page: Page): Promise<VirtualAuthenticator> {
  const session = await page.context().newCDPSession(page)
  await session.send('WebAuthn.enable')
  const { authenticatorId } = await session.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  })
  return { session, id: authenticatorId }
}

/** A fresh single-use enrollment link for `origin`, printed by the CLI like an operator's. */
export function enrollmentLink(origin: string): string {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir)
    throw new Error(`${DATA_DIR_ENV} is unset; run the specs through playwright.config.ts`)
  const result = spawnSync(
    'uv',
    ['run', '--frozen', 'labhq', 'passkey', 'enroll', '--url', origin],
    { cwd: repoRoot, encoding: 'utf-8', env: { ...process.env, LABHQ_DATA_DIR: dataDir } },
  )
  if (result.status !== 0) {
    throw new Error(`labhq passkey enroll failed (${result.status}):\n${result.stderr}`)
  }
  // The link is the first line on stdout; uv may print its own progress on stderr.
  const link = result.stdout.trim().split('\n')[0] ?? ''
  if (!link.startsWith(`${origin}/enroll#`))
    throw new Error(`unexpected enrollment output: ${link}`)
  return link
}

export async function enrollThroughUi(page: Page, link: string, name: string): Promise<void> {
  await page.goto(link)
  await page.getByTestId('passkey-name').fill(name)
  await page.getByTestId('create-passkey').click()
  await expect(page.getByTestId('enrolled')).toBeVisible()
}

export async function signInThroughUi(page: Page): Promise<void> {
  await page.getByTestId('sign-in').click()
}

interface AuthFixtures {
  authenticator: VirtualAuthenticator
  signedInPage: Page
}

export const test = base.extend<AuthFixtures>({
  // Every page request of a spec using this `test` goes to localhost, where passkeys work.
  baseURL: async ({ baseURL }, use) => {
    await use(localhostOrigin(baseURL))
  },
  // Automatic: a spec cannot enroll or sign in without one, and forgetting it fails oddly.
  authenticator: [
    async ({ page }, use) => {
      const authenticator = await addVirtualAuthenticator(page)
      await use(authenticator)
      await authenticator.session.send('WebAuthn.removeVirtualAuthenticator', {
        authenticatorId: authenticator.id,
      })
    },
    { auto: true },
  ],
  signedInPage: async ({ page, baseURL }, use) => {
    const origin = localhostOrigin(baseURL)
    await enrollThroughUi(page, enrollmentLink(origin), 'e2e')
    await page.getByTestId('go-sign-in').click()
    await signInThroughUi(page)
    await expect(page).toHaveURL(/\/today$/)
    await use(page)
  },
})

export { expect }
