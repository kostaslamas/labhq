import { expect, test } from './support/auth.ts'

test('the owner assigns a main and backup agent to the global CEO', async ({
  signedInPage: page,
}) => {
  await page.goto('/projects')
  const assignment = page.getByTestId('ceo-assignment')
  await expect(assignment).toBeVisible()
  await assignment.getByTestId('ceo-primary').selectOption('claude')
  await assignment.getByTestId('ceo-backup').selectOption('codex')
  await assignment.getByTestId('ceo-save').click()
  await expect(assignment.getByTestId('ceo-saved')).toBeVisible()

  await page.reload()
  await expect(assignment.getByTestId('ceo-primary')).toHaveValue('claude')
  await expect(assignment.getByTestId('ceo-backup')).toHaveValue('codex')
})
