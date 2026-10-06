import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, test } from './support/auth.ts'
import { DATA_DIR_ENV } from './support/server.ts'

const repoRoot = fileURLToPath(new URL('../../', import.meta.url))

function script(...args: string[]): Record<string, number> {
  const dataDir = process.env[DATA_DIR_ENV]
  if (!dataDir) throw new Error(`${DATA_DIR_ENV} is unset`)
  const result = spawnSync(
    'uv',
    ['run', '--frozen', 'python', '-m', 'tools.e2e_ceo_report', dataDir, ...args],
    { cwd: repoRoot, encoding: 'utf-8' },
  )
  if (result.status !== 0) throw new Error(`tools.e2e_ceo_report failed:\n${result.stderr}`)
  return JSON.parse(result.stdout.trim().split('\n').at(-1) ?? '{}') as Record<string, number>
}

// Other specs share the database, and Today's delivered list is pixel-compared: a task this
// spec accepted must not stay done.
let mine: number[] = []
function cancel(...ids: number[]): void {
  if (ids.length) script('--cancel', ...ids.map(String))
  mine = mine.filter((id) => !ids.includes(id))
}
test.afterAll(() => cancel(...mine))

test('the owner accepts and returns reported root tasks from the CEO chat', async ({
  signedInPage: page,
}) => {
  const tasks = script('Ship the landing page', 'Ship the search page')
  mine = Object.values(tasks)
  await page.goto('/ceo')

  const accepted = page.getByTestId('ceo-report').filter({ hasText: 'Ship the landing page' })
  await expect(accepted).toBeVisible()
  await accepted.getByTestId('report-accept').click()
  await expect(accepted.getByTestId('report-accept')).toHaveCount(0)
  cancel(tasks['Ship the landing page']!)

  const returned = page.getByTestId('ceo-report').filter({ hasText: 'Ship the search page' })
  await returned.getByTestId('report-return').click()
  await returned.getByTestId('report-feedback').fill('Add filters first.')
  await returned.getByTestId('report-send-back').click()
  await expect(returned.getByTestId('report-return')).toHaveCount(0)

  await page.reload()
  await expect(page.getByTestId('ceo-report').filter({ hasText: 'Ship the' })).toHaveCount(2)
  await expect(page.getByTestId('report-return')).toHaveCount(0)
})
