import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'

import { isErrorEnvelope, type components } from '@/api'
import { authClient } from '@/auth/client'

export type Scope = components['schemas']['ScanScopeOut']
export type ScanRoot = components['schemas']['RootOut']

// Why a change was not made; each maps to one sentence in `sessions.errors`.
export type ChangeFailure = 'refused' | 'invalid' | 'not_found' | 'failed' | 'network'

const FAILURE_BY_CODE: Partial<Record<string, ChangeFailure>> = {
  root_invalid: 'invalid',
  root_not_found: 'not_found',
  step_up_required: 'refused',
  challenge_invalid: 'refused',
  assertion_invalid: 'refused',
  credential_unknown: 'refused',
  credential_revoked: 'refused',
  origin_not_allowed: 'refused',
  malformed_credential: 'refused',
}

export type Change =
  | { ok: true; scope: Scope; warning: string | null }
  | { ok: false; failure: ChangeFailure; detail: string | null }

function refusal(error: unknown): Change {
  const code = isErrorEnvelope(error) ? error.error.code : ''
  const detail = isErrorEnvelope(error) && code === 'root_invalid' ? error.error.message : null
  return { ok: false, failure: FAILURE_BY_CODE[code] ?? 'failed', detail }
}

/** Add a folder; the passkey assertion is for the purpose `session_scan:roots`. */
export async function addRoot(
  path: string,
  credential: AuthenticationResponseJSON,
): Promise<Change> {
  try {
    const { data, error } = await authClient().POST('/api/session-scan/roots', {
      body: { path, credential: { ...credential } },
    })
    if (data === undefined) return refusal(error)
    return { ok: true, scope: data.scope, warning: data.warning }
  } catch {
    return { ok: false, failure: 'network', detail: null }
  }
}

export async function removeRoot(
  path: string,
  credential: AuthenticationResponseJSON,
): Promise<Change> {
  try {
    const { data, error } = await authClient().DELETE('/api/session-scan/roots', {
      body: { path, credential: { ...credential } },
    })
    return data === undefined ? refusal(error) : { ok: true, scope: data, warning: null }
  } catch {
    return { ok: false, failure: 'network', detail: null }
  }
}
