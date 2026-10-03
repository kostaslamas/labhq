import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeServer, unauthorized } from '@/auth/__fixtures__/server'

import {
  keyBytes,
  PushFailure,
  subscribeDevice,
  unsubscribeDevice,
  type PushBrowser,
} from './subscription'

const ENDPOINT = 'https://push.example.test/send/abc'

function fakeBrowser(permission: NotificationPermission = 'granted') {
  const pushSubscription = {
    endpoint: ENDPOINT,
    toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: 'BKey', auth: 'secret' } }),
    unsubscribe: vi.fn(() => Promise.resolve(true)),
  }
  const pushManager = {
    getSubscription: vi.fn(() => Promise.resolve<unknown>(null)),
    subscribe: vi.fn(() => Promise.resolve(pushSubscription)),
  }
  const browser: PushBrowser = {
    requestPermission: vi.fn(() => Promise.resolve(permission)),
    registration: () => Promise.resolve({ pushManager } as unknown as ServiceWorkerRegistration),
  }
  return { browser, pushManager, pushSubscription }
}

const status = { status: 200, body: { public_key: 'AQID', active: true } }

describe('subscribeDevice', () => {
  let routes: Parameters<typeof fakeServer>[0]

  beforeEach(() => {
    routes = {
      'GET /api/push/status': () => status,
      'POST /api/push/subscriptions': () => ({ status: 204 }),
    }
  })

  it('subscribes with the server key and sends the endpoint and keys, with the write header', async () => {
    const { client, requests } = fakeServer(routes)
    const { browser, pushManager } = fakeBrowser()

    await subscribeDevice(client, browser)

    expect(pushManager.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: keyBytes('AQID'),
    })
    const saved = requests.find((request) => request.path === '/api/push/subscriptions')
    expect(saved?.body).toEqual({ endpoint: ENDPOINT, keys: { p256dh: 'BKey', auth: 'secret' } })
    expect(saved?.headers.get('X-Labhq-Request')).toBe('1')
  })

  it('does not subscribe the browser when permission is refused', async () => {
    const { client, requests } = fakeServer(routes)
    const { browser, pushManager } = fakeBrowser('denied')

    await expect(subscribeDevice(client, browser)).rejects.toMatchObject({ kind: 'permission' })

    expect(pushManager.subscribe).not.toHaveBeenCalled()
    expect(requests.map((request) => request.path)).toEqual(['/api/push/status'])
  })

  it('asks for a new sign-in when the session ended', async () => {
    routes['GET /api/push/status'] = () => unauthorized
    const { client } = fakeServer(routes)

    await expect(subscribeDevice(client, fakeBrowser().browser)).rejects.toMatchObject({
      kind: 'sign_in',
    })
  })

  it('reports a server that refuses the subscription', async () => {
    routes['POST /api/push/subscriptions'] = () => ({
      status: 500,
      body: { error: { code: 'boom', message: 'no' } },
    })
    const { client } = fakeServer(routes)

    const failure = await subscribeDevice(client, fakeBrowser().browser).catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(PushFailure)
    expect(failure).toMatchObject({ kind: 'server' })
  })
})

describe('unsubscribeDevice', () => {
  it('removes the endpoint on the server, then unsubscribes the browser', async () => {
    const { client, requests } = fakeServer({
      'POST /api/push/subscriptions/remove': () => ({ status: 204 }),
    })
    const { browser, pushManager, pushSubscription } = fakeBrowser()
    pushManager.getSubscription.mockResolvedValue(pushSubscription)

    await unsubscribeDevice(client, browser)

    expect(requests[0]?.body).toEqual({ endpoint: ENDPOINT })
    expect(pushSubscription.unsubscribe).toHaveBeenCalled()
  })

  it('does nothing when this browser has no subscription', async () => {
    const { client, requests } = fakeServer({})

    await unsubscribeDevice(client, fakeBrowser().browser)

    expect(requests).toEqual([])
  })
})

describe('keyBytes', () => {
  it('decodes base64url without padding', () => {
    expect([...keyBytes('AQID')]).toEqual([1, 2, 3])
    expect([...keyBytes('-_8')]).toEqual([251, 255])
  })
})
