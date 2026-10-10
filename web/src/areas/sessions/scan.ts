import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'

import { isErrorEnvelope, type components } from '@/api'
import { authClient } from '@/auth/client'

export type Scope = components['schemas']['ScopeOut']
export type FolderRow = components['schemas']['FolderOut']
export type FoundProject = components['schemas']['FoundOut']

// Why a change was not made; each maps to one sentence in `sessions.errors`.
export type ChangeFailure = 'refused' | 'invalid' | 'failed' | 'network'

const FAILURE_BY_CODE: Partial<Record<string, ChangeFailure>> = {
  root_invalid: 'invalid',
  step_up_required: 'refused',
  challenge_invalid: 'refused',
  assertion_invalid: 'refused',
  credential_unknown: 'refused',
  credential_revoked: 'refused',
  origin_not_allowed: 'refused',
  malformed_credential: 'refused',
}

export type Change =
  | { ok: true; scope: Scope; warnings: string[] }
  | { ok: false; failure: ChangeFailure; detail: string | null }

function refusal(error: unknown): Change {
  const code = isErrorEnvelope(error) ? error.error.code : ''
  const detail = isErrorEnvelope(error) && code === 'root_invalid' ? error.error.message : null
  return { ok: false, failure: FAILURE_BY_CODE[code] ?? 'failed', detail }
}

export async function loadScope(): Promise<Scope | null> {
  const { data } = await authClient().GET('/api/inventory/roots')
  return data ?? null
}

/** Run a scan now (no model, no transcript read) and return the scope with its result. */
export async function scanNow(): Promise<Scope | null> {
  const scanned = await authClient().POST('/api/inventory/scan')
  if (scanned.data === undefined) return null
  return loadScope()
}

/** Save the stored lists whole; the passkey assertion is for `session_scan:roots`. */
export async function saveLists(
  roots: string[],
  exclude: string[],
  credential: AuthenticationResponseJSON,
): Promise<Change> {
  try {
    const { data, error } = await authClient().PUT('/api/inventory/roots', {
      body: { roots, exclude, credential: { ...credential } },
    })
    return data === undefined
      ? refusal(error)
      : { ok: true, scope: data.scope, warnings: data.warnings }
  } catch {
    return { ok: false, failure: 'network', detail: null }
  }
}

/** "Not interested" in a found project: the scan skips its folder from now on. */
export async function excludeFolder(
  path: string,
  credential: AuthenticationResponseJSON,
): Promise<Change> {
  try {
    const { data, error } = await authClient().POST('/api/inventory/exclusions', {
      body: { path, credential: { ...credential } },
    })
    return data === undefined ? refusal(error) : { ok: true, scope: data, warnings: [] }
  } catch {
    return { ok: false, failure: 'network', detail: null }
  }
}
