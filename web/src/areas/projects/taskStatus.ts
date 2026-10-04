import type { BackendStatus } from '@/api'

// Literal keys, so `npm run i18n:check` sees every message this area names.
export const taskStatusLabels: Record<BackendStatus<'task_status'>, { labelKey: string }> = {
  backlog: { labelKey: 'projects.taskStatus.backlog' },
  todo: { labelKey: 'projects.taskStatus.todo' },
  in_progress: { labelKey: 'projects.taskStatus.in_progress' },
  in_review: { labelKey: 'projects.taskStatus.in_review' },
  blocked: { labelKey: 'projects.taskStatus.blocked' },
  done: { labelKey: 'projects.taskStatus.done' },
  cancelled: { labelKey: 'projects.taskStatus.cancelled' },
}
