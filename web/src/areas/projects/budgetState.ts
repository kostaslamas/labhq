import type { components } from '@/api'
import type { UiState } from '@/status'

export type BudgetVerdict = components['schemas']['Budget']['state']

// `allow` is the normal case and shows no badge. The other two reuse the shared vocabulary:
// a warning asks for the owner's attention, a stop is work that cannot start.
export const budgetStates: Record<BudgetVerdict, { state: UiState | null; labelKey: string }> = {
  allow: { state: null, labelKey: 'projects.budget.allow' },
  warn: { state: 'waiting_on_you', labelKey: 'projects.budget.warn' },
  stop: { state: 'blocked', labelKey: 'projects.budget.stop' },
}
