import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'

import { isErrorEnvelope, type components } from '@/api'
import { authClient } from '@/auth/client'

export type Channel = components['schemas']['ChannelOut']
export type ChannelKind = components['schemas']['KindOut']

// Why a change was not made; each maps to one sentence in `channels.errors`.
export type ChangeFailure = 'refused' | 'invalid' | 'not_found' | 'failed' | 'network'

const FAILURE_BY_CODE: Partial<Record<string, ChangeFailure>> = {
  channel_invalid: 'invalid',
  channel_not_found: 'not_found',
  step_up_required: 'refused',
  challenge_invalid: 'refused',
  assertion_invalid: 'refused',
  credential_unknown: 'refused',
  credential_revoked: 'refused',
  origin_not_allowed: 'refused',
  malformed_credential: 'refused',
}

export type Change<T> = { ok: true; value: T } | { ok: false; failure: ChangeFailure }

function failureOf(error: unknown): ChangeFailure {
  const code = isErrorEnvelope(error) ? error.error.code : ''
  return FAILURE_BY_CODE[code] ?? 'failed'
}

/** Add a channel; `values` may hold a bot token, which is sent once and never shown again. */
export async function addChannel(
  kind: string,
  name: string,
  values: Record<string, string>,
  credential: AuthenticationResponseJSON,
): Promise<Change<{ channel: Channel; error: string | null }>> {
  try {
    const { data, error } = await authClient().POST('/api/channels', {
      body: { kind, name, values, credential: { ...credential } },
    })
    return data !== undefined ? { ok: true, value: data } : { ok: false, failure: failureOf(error) }
  } catch {
    return { ok: false, failure: 'network' }
  }
}

export async function testChannel(
  id: number,
): Promise<Change<{ channel: Channel; error: string | null }>> {
  try {
    const { data, error } = await authClient().POST('/api/channels/{channel_id}/test', {
      params: { path: { channel_id: id } },
    })
    return data !== undefined ? { ok: true, value: data } : { ok: false, failure: failureOf(error) }
  } catch {
    return { ok: false, failure: 'network' }
  }
}

export async function switchChannel(
  id: number,
  enabled: boolean,
  credential: AuthenticationResponseJSON,
): Promise<Change<Channel>> {
  try {
    const { data, error } = await authClient().PATCH('/api/channels/{channel_id}', {
      params: { path: { channel_id: id } },
      body: { enabled, credential: { ...credential } },
    })
    return data !== undefined ? { ok: true, value: data } : { ok: false, failure: failureOf(error) }
  } catch {
    return { ok: false, failure: 'network' }
  }
}

export async function removeChannel(
  id: number,
  credential: AuthenticationResponseJSON,
): Promise<Change<null>> {
  try {
    const { response, error } = await authClient().DELETE('/api/channels/{channel_id}', {
      params: { path: { channel_id: id } },
      body: { credential: { ...credential } },
    })
    return response.ok ? { ok: true, value: null } : { ok: false, failure: failureOf(error) }
  } catch {
    return { ok: false, failure: 'network' }
  }
}
