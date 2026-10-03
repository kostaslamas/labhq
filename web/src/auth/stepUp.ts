import { readonly, ref } from 'vue'
import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'

import { AuthFailure, assertionFor, type AuthFailureKind } from './ceremonies'

/**
 * Ask the owner for a passkey assertion for one decision, for example `approval:42`.
 *
 * A heavy approval is accepted by the server only with this assertion in the same request; a
 * session alone never passes. The assertion is single use and expires within minutes, so ask
 * when the person presses the button, not when the page opens.
 */
export function useStepUp() {
  const pending = ref(false)
  const failure = ref<AuthFailureKind | null>(null)

  async function requestAssertion(purpose: string): Promise<AuthenticationResponseJSON | null> {
    pending.value = true
    failure.value = null
    try {
      return await assertionFor(purpose)
    } catch (error) {
      failure.value = error instanceof AuthFailure ? error.kind : 'rejected'
      return null
    } finally {
      pending.value = false
    }
  }

  return { requestAssertion, pending: readonly(pending), failure: readonly(failure) }
}
