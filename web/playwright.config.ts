import { defineConfig, devices } from '@playwright/test'

import { BASE_URL_ENV } from './e2e/support/server.ts'

export default defineConfig({
  testDir: './e2e',
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  // Seeds a temporary labhq and serves the built UI from it (e2e/support/server.ts).
  globalSetup: './e2e/support/server.ts',
  use: {
    // Set by the global setup; workers load this file again after it has run.
    baseURL: process.env[BASE_URL_ENV],
    locale: 'en-US',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
      },
    },
  ],
})
