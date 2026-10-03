import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'

import { api, type ApiClient } from '@/api'

import { authClient, setAuthClient } from './client'
import { installAuthGuard, installUnauthorizedRedirect } from './guard'

export interface AuthOptions {
  client?: ApiClient
}

/** Protect every non-public route and leave for login when the session ends. */
export function installAuth(router: Router, pinia: Pinia, options: AuthOptions = {}): void {
  const client = options.client ?? api
  setAuthClient(client)
  installAuthGuard(router, pinia)
  installUnauthorizedRedirect(authClient(), router, pinia)
}

export { AuthFailure, type AuthFailureKind } from './ceremonies'
export { useStepUp } from './stepUp'
export { useAuthStore } from './store'
export { loginRedirect, safeNext } from './guard'
