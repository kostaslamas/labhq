import { useI18n } from 'vue-i18n'

import { AuthFailure, type AuthFailureKind } from '@/auth'

const MESSAGE_KEYS: Record<AuthFailureKind, string> = {
  cancelled: 'auth.errors.cancelled',
  unsupported: 'auth.errors.unsupported',
  no_passkey: 'auth.errors.no_passkey',
  enrollment_link_invalid: 'auth.errors.enrollment_link_invalid',
  origin_not_allowed: 'auth.errors.origin_not_allowed',
  rejected: 'auth.errors.rejected',
  network: 'auth.errors.network',
}

/** The sentence for a failed ceremony, in the interface language. */
export function useFailureMessage() {
  const { t } = useI18n()
  return (error: unknown): string =>
    t(MESSAGE_KEYS[error instanceof AuthFailure ? error.kind : 'rejected'])
}
