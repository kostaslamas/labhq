import type { Middleware } from 'openapi-fetch'
import type { Pinia } from 'pinia'
import type { RouteLocationNormalized, RouteLocationRaw, Router } from 'vue-router'

import type { ApiClient } from '@/api'

import { useAuthStore } from './store'

export const LOGIN_ROUTE = 'login'
const AUTH_API_PREFIX = '/api/auth/'

/** Only a path inside this app is a valid place to return to; anything else is dropped. */
export function safeNext(next: unknown): string | undefined {
  return typeof next === 'string' && next.startsWith('/') && !next.startsWith('//')
    ? next
    : undefined
}

export function loginRedirect(to: RouteLocationNormalized): RouteLocationRaw {
  return { name: LOGIN_ROUTE, query: to.fullPath === '/' ? {} : { next: to.fullPath } }
}

/**
 * Sends a visitor without a session to the login page. A route opts out with
 * `meta.public`; every other route, in every area, is protected by default.
 */
export function installAuthGuard(router: Router, pinia: Pinia): void {
  const auth = useAuthStore(pinia)
  router.beforeEach(async (to) => {
    if (to.meta.public) return true
    await auth.ensureLoaded()
    return auth.signedIn ? true : loginRedirect(to)
  })
}

/** An expired or revoked session answers 401 mid-use: go to login instead of showing errors. */
export function installUnauthorizedRedirect(client: ApiClient, router: Router, pinia: Pinia): void {
  const auth = useAuthStore(pinia)
  const middleware: Middleware = {
    async onResponse({ response }) {
      const path = new URL(response.url, window.location.origin).pathname
      if (response.status === 401 && !path.startsWith(AUTH_API_PREFIX) && auth.signedIn) {
        auth.markSignedOut()
        await router.push(loginRedirect(router.currentRoute.value))
      }
      return response
    },
  }
  client.use(middleware)
}
