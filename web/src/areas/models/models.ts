import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'

import { isErrorEnvelope, type components } from '@/api'
import { authClient } from '@/auth/client'

export type Policy = components['schemas']['PolicyOut']
export type PolicyRow = components['schemas']['RowOut']
export type ModelCost = components['schemas']['CostOut']

// Why a save did not happen; each maps to one sentence in `models.errors`.
export type SaveFailure = 'refused' | 'invalid' | 'failed' | 'network'

const FAILURE_BY_CODE: Partial<Record<string, SaveFailure>> = {
  model_policy_invalid: 'invalid',
  step_up_required: 'refused',
  challenge_invalid: 'refused',
  assertion_invalid: 'refused',
  credential_unknown: 'refused',
  credential_revoked: 'refused',
  origin_not_allowed: 'refused',
  malformed_credential: 'refused',
}

export type Saved = { ok: true; value: Policy } | { ok: false; failure: SaveFailure }

/** Save the edited rows; the passkey assertion is for the purpose `models:policy`. */
export async function savePolicy(
  rows: PolicyRow[],
  credential: AuthenticationResponseJSON,
): Promise<Saved> {
  try {
    const { data, error } = await authClient().PUT('/api/models', {
      body: {
        rows: Object.fromEntries(
          rows.map((r) => [
            r.key,
            { model: r.model, effort: r.effort, max_output_tokens: r.max_output_tokens },
          ]),
        ),
        credential: { ...credential },
      },
    })
    if (data !== undefined) return { ok: true, value: data }
    const code = isErrorEnvelope(error) ? error.error.code : ''
    return { ok: false, failure: FAILURE_BY_CODE[code] ?? 'failed' }
  } catch {
    return { ok: false, failure: 'network' }
  }
}
