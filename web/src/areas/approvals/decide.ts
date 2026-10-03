import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'

import { isErrorEnvelope, type components } from '@/api'
import { authClient } from '@/auth/client'

export type Approval = components['schemas']['ApprovalOut']
export type Decision = components['schemas']['DecisionBody']['decision']

// Why a decision was not recorded; each maps to one sentence in `approvals.errors`.
export type DecisionFailure =
  'refused' | 'step_up_required' | 'already_decided' | 'not_allowed' | 'failed' | 'network'

const FAILURE_BY_CODE: Partial<Record<string, DecisionFailure>> = {
  step_up_required: 'step_up_required',
  confirmation_not_allowed: 'not_allowed',
  approval_not_pending: 'already_decided',
  // The passkey step failed on the server: an unknown, spent or mismatched challenge.
  challenge_invalid: 'refused',
  assertion_invalid: 'refused',
  credential_unknown: 'refused',
  credential_revoked: 'refused',
  origin_not_allowed: 'refused',
  malformed_credential: 'refused',
}

export type DecisionResult =
  { ok: true; approval: Approval } | { ok: false; failure: DecisionFailure }

/**
 * Send one decision. `key` names the user's intent: a retry of the same intent reuses it, so
 * the server answers with the decision it already made instead of deciding twice.
 */
export async function submitDecision(
  id: number,
  decision: Decision,
  key: string,
  credential?: AuthenticationResponseJSON,
): Promise<DecisionResult> {
  try {
    const { data, error } = await authClient().POST('/api/approvals/{approval_id}/decision', {
      params: { path: { approval_id: id }, header: { 'idempotency-key': key } },
      body: { decision, credential: credential ? { ...credential } : null },
    })
    if (data !== undefined) return { ok: true, approval: data }
    const code = isErrorEnvelope(error) ? error.error.code : ''
    return { ok: false, failure: FAILURE_BY_CODE[code] ?? 'failed' }
  } catch {
    return { ok: false, failure: 'network' }
  }
}
