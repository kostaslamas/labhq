import { api, type ApiClient } from '@/api'

// The store and the ceremonies share one client; tests swap it for one with a fake fetch.
let current: ApiClient = api

export function authClient(): ApiClient {
  return current
}

export function setAuthClient(client: ApiClient): void {
  current = client
}
