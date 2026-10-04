import { isErrorEnvelope } from '@/api'

// Server error codes of the add-project and add-agent routes, each with one sentence in
// `projects.errors`; any other code shows the generic one.
const KNOWN = new Set([
  'not_a_repository',
  'repo_path_not_absolute',
  'project_exists',
  'unknown_kind',
  'reporting_line',
  'agent_not_valid',
  'project_not_found',
  'validation_error',
])

export function errorKey(error: unknown): string {
  const code = isErrorEnvelope(error) ? error.error.code : ''
  return `projects.errors.${KNOWN.has(code) ? code : 'failed'}`
}
