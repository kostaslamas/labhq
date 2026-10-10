import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { expect, test } from './support/auth.ts'

function repository(path: string): void {
  mkdirSync(path, { recursive: true })
  execFileSync('git', ['init', '-q', '-b', 'main'], { cwd: path })
  execFileSync(
    'git',
    [
      '-c',
      'user.email=e2e@example.test',
      '-c',
      'user.name=e2e',
      'commit',
      '-q',
      '--allow-empty',
      '-m',
      'start',
    ],
    { cwd: path },
  )
}

test('the owner sets a folder on /projects, finds projects in it, adds one and skips another', async ({
  signedInPage: page,
}) => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'labhq-scan-')))
  repository(join(root, 'wanted-site'))
  repository(join(root, 'skipped-site'))

  await page.goto('/projects?panel=scan')
  await expect(page.getByTestId('machine-wide')).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true)

  // The folder is set with a passkey; the first look runs once, by itself.
  await page.getByTestId('root-path').fill(root)
  await page.getByTestId('add-button').click()
  await expect(page.getByTestId(`root-${root}`)).toBeVisible()
  await expect(page.getByTestId('found-wanted-site')).toContainText('git')
  await expect(page.getByTestId('found-skipped-site')).toBeVisible()
  await expect(page.getByTestId('left-out')).toBeVisible()

  // "Not interested" records an exclusion and the project leaves the list for good.
  await page.getByTestId('found-skipped-site').getByTestId('found-skip').click()
  await expect(page.getByTestId('found-skipped-site')).toHaveCount(0)
  await page.getByTestId('scan-now').click()
  await expect(page.getByTestId('found-wanted-site')).toBeVisible()
  await expect(page.getByTestId('found-skipped-site')).toHaveCount(0)

  // "Add project" opens the existing form with the folder filled in.
  await page.getByTestId('found-wanted-site').getByTestId('found-add').click()
  await expect(page.getByTestId('add-project-form').locator('input[name="repo_path"]')).toHaveValue(
    join(root, 'wanted-site'),
  )
  await page.getByTestId('add-project-submit').click()
  await expect(page).toHaveURL(/\/projects\/\d+$/)

  // Leave the shared seed as found for the specs that run after this one.
  await page.goto('/projects')
  await expect(page.getByTestId('roots')).toBeVisible()
  const removals = page.getByTestId('session-scan').getByRole('button', { name: 'Remove' })
  for (let left = await removals.count(); left > 0; left--) {
    await removals.first().click()
    await expect(removals).toHaveCount(left - 1)
  }
  await expect(page.getByTestId('machine-wide')).toBeVisible()
})
