import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { createApiClient } from '@/api'

import { fakeServer, unauthorized } from './__fixtures__/server'
import { setAuthClient } from './client'
import { installAuth } from './index'
import { safeNext } from './guard'
import { useAuthStore } from './store'

const Page = { template: '<p />' }

function appRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/today', name: 'today', component: Page },
      { path: '/login', name: 'login', component: Page, meta: { public: true } },
      { path: '/enroll', name: 'enroll', component: Page, meta: { public: true } },
    ],
  })
}

function signedOut() {
  return { status: 200, body: { authenticated: false, enrolled: true } }
}

describe('auth guard', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('sends a visitor without a session to login and remembers where they were going', async () => {
    const { client } = fakeServer({ 'GET /api/auth/status': signedOut })
    const router = appRouter()
    installAuth(router, createPinia(), { client })

    await router.push('/today')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/today')
  })

  it('lets a signed-in visitor through', async () => {
    const { client } = fakeServer({
      'GET /api/auth/status': () => ({ body: { authenticated: true, enrolled: true } }),
    })
    const router = appRouter()
    installAuth(router, createPinia(), { client })

    await router.push('/today')

    expect(router.currentRoute.value.name).toBe('today')
  })

  it('never asks the server about a public route', async () => {
    const { client, requests } = fakeServer({})
    const router = appRouter()
    installAuth(router, createPinia(), { client })

    await router.push('/enroll')

    expect(router.currentRoute.value.name).toBe('enroll')
    expect(requests).toEqual([])
  })

  it('treats an unreachable server as signed out', async () => {
    const failing = createApiClient('http://labhq.test', () => Promise.reject(new Error('offline')))
    const router = appRouter()
    installAuth(router, createPinia(), { client: failing })

    await router.push('/today')

    expect(router.currentRoute.value.name).toBe('login')
  })

  it('goes to login when the session ends in the middle of use', async () => {
    let expired = false
    const { client } = fakeServer({
      'GET /api/auth/status': () => ({ body: { authenticated: true, enrolled: true } }),
      'GET /api/vocabulary': () => (expired ? unauthorized : { body: {} }),
    })
    const pinia = createPinia()
    const router = appRouter()
    installAuth(router, pinia, { client })
    await router.push('/today')
    expect(router.currentRoute.value.name).toBe('today')

    expired = true
    await client.GET('/api/vocabulary')

    expect(router.currentRoute.value.name).toBe('login')
    expect(useAuthStore(pinia).signedIn).toBe(false)
  })

  it('signs out', async () => {
    const { client } = fakeServer({ 'POST /api/auth/logout': () => ({ body: {} }) })
    setAuthClient(client)
    const store = useAuthStore()
    store.state = 'signed_in'

    await store.signOut()

    expect(store.signedIn).toBe(false)
  })
})

describe('safeNext', () => {
  it.each([
    ['/projects', '/projects'],
    ['//evil.test', undefined],
    ['https://evil.test', undefined],
    [undefined, undefined],
    [['/a'], undefined],
  ])('%s -> %s', (input, expected) => {
    expect(safeNext(input)).toBe(expected)
  })
})
