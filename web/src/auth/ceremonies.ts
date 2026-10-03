// The browser half of each WebAuthn ceremony: fetch options, ask the authenticator, send the
// answer. Nothing here is logged or stored; the credential goes straight back to the server.
import {
  browserSupportsWebAuthn,
  startAuthentication,
  startRegistration,
  type AuthenticationResponseJSON,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
  type RegistrationResponseJSON,
} from '@simplewebauthn/browser'

import { isErrorEnvelope } from '@/api'

import { authClient } from './client'

export type AuthFailureKind =
  | 'cancelled'
  | 'unsupported'
  | 'no_passkey'
  | 'enrollment_link_invalid'
  | 'origin_not_allowed'
  | 'rejected'
  | 'network'

export class AuthFailure extends Error {
  readonly kind: AuthFailureKind

  constructor(kind: AuthFailureKind) {
    super(kind)
    this.kind = kind
  }
}

const SERVER_CODES: Partial<Record<string, AuthFailureKind>> = {
  no_passkey: 'no_passkey',
  enrollment_link_invalid: 'enrollment_link_invalid',
  origin_not_allowed: 'origin_not_allowed',
}

export function failureFromServer(error: unknown): AuthFailure {
  if (isErrorEnvelope(error)) return new AuthFailure(SERVER_CODES[error.error.code] ?? 'rejected')
  return new AuthFailure('network')
}

function failureFromBrowser(error: unknown): AuthFailure {
  if (error instanceof AuthFailure) return error
  const name = error instanceof Error ? error.name : ''
  // The person dismissed the prompt, or it timed out: not an error worth a stack trace.
  if (name === 'NotAllowedError' || name === 'AbortError') return new AuthFailure('cancelled')
  return new AuthFailure('rejected')
}

function requireWebAuthn(): void {
  if (!browserSupportsWebAuthn()) throw new AuthFailure('unsupported')
}

async function unwrap<T>(request: Promise<{ data?: T; error?: unknown }>): Promise<T> {
  let result: { data?: T; error?: unknown }
  try {
    result = await request
  } catch {
    throw new AuthFailure('network')
  }
  if (result.data === undefined) throw failureFromServer(result.error)
  return result.data
}

export async function signInWithPasskey(): Promise<void> {
  requireWebAuthn()
  const client = authClient()
  const options = await unwrap(client.POST('/api/auth/login/options'))
  let credential: AuthenticationResponseJSON
  try {
    credential = await startAuthentication({
      optionsJSON: options as unknown as PublicKeyCredentialRequestOptionsJSON,
    })
  } catch (error) {
    throw failureFromBrowser(error)
  }
  await unwrap(client.POST('/api/auth/login/verify', { body: { credential: { ...credential } } }))
}

export async function enrollPasskey(token: string, name: string): Promise<void> {
  requireWebAuthn()
  const client = authClient()
  const options = await unwrap(client.POST('/api/auth/enroll/options', { body: { token } }))
  let credential: RegistrationResponseJSON
  try {
    credential = await startRegistration({
      optionsJSON: options as unknown as PublicKeyCredentialCreationOptionsJSON,
    })
  } catch (error) {
    throw failureFromBrowser(error)
  }
  await unwrap(
    client.POST('/api/auth/enroll/verify', {
      body: { token, credential: { ...credential }, name },
    }),
  )
}

/** A fresh assertion bound to `purpose`, for the server to check once with the decision. */
export async function assertionFor(purpose: string): Promise<AuthenticationResponseJSON> {
  requireWebAuthn()
  const options = await unwrap(
    authClient().POST('/api/auth/step-up/options', { body: { purpose } }),
  )
  try {
    return await startAuthentication({
      optionsJSON: options as unknown as PublicKeyCredentialRequestOptionsJSON,
    })
  } catch (error) {
    throw failureFromBrowser(error)
  }
}
