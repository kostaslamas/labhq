import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { runInNewContext } from 'node:vm'

import { describe, expect, it, vi } from 'vitest'

// The worker is plain JavaScript served from the site root. It is evaluated here against a fake
// worker scope that records the listeners it registers, then driven with fake events.
const source = readFileSync(resolve(import.meta.dirname, '../../public/sw.js'), 'utf8')
const ORIGIN = 'https://labhq.example.org'

type Listener = (event: Record<string, unknown>) => void

interface FakeClient {
  navigate: ReturnType<typeof vi.fn>
  focus: ReturnType<typeof vi.fn>
}

function loadWorker(windows: FakeClient[] = []) {
  const listeners = new Map<string, Listener>()
  const scope = {
    addEventListener: (type: string, listener: Listener) => listeners.set(type, listener),
    registration: {
      showNotification: vi.fn<(title: string, options?: unknown) => Promise<void>>(() =>
        Promise.resolve(),
      ),
    },
    clients: {
      matchAll: vi.fn(() => Promise.resolve(windows)),
      openWindow: vi.fn(() => Promise.resolve(null)),
      claim: vi.fn(() => Promise.resolve()),
    },
    location: { origin: ORIGIN },
    skipWaiting: vi.fn(),
  }
  // A new context is a worker-like global: the file sees only `self` and what is passed in.
  runInNewContext(source, { self: scope, URL })

  async function dispatch(type: string, event: Record<string, unknown>): Promise<void> {
    const pending: Promise<unknown>[] = []
    listeners.get(type)?.({ ...event, waitUntil: (work: Promise<unknown>) => pending.push(work) })
    await Promise.all(pending)
  }
  return { scope, dispatch }
}

function tap(clickUrl: string | null | undefined) {
  const notification = {
    close: vi.fn(),
    data: clickUrl === undefined ? undefined : { click_url: clickUrl },
  }
  return { notification }
}

function pushOf(payload: unknown) {
  return { data: { json: () => payload } }
}

describe('service worker', () => {
  it('opens the click_url of the tapped notification and closes the notification', async () => {
    const { scope, dispatch } = loadWorker()
    const event = tap('/approve/42')

    await dispatch('notificationclick', event)

    expect(event.notification.close).toHaveBeenCalled()
    expect(scope.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/approve/42`)
  })

  it('reuses a window of the installed app instead of opening a second one', async () => {
    const client: FakeClient = {
      navigate: vi.fn(() => Promise.resolve(null)),
      focus: vi.fn(() => Promise.resolve(null)),
    }
    const { scope, dispatch } = loadWorker([client])

    await dispatch('notificationclick', tap('/approve/7'))

    expect(client.navigate).toHaveBeenCalledWith(`${ORIGIN}/approve/7`)
    expect(client.focus).toHaveBeenCalled()
    expect(scope.clients.openWindow).not.toHaveBeenCalled()
  })

  it('opens a new window when no existing one can be navigated', async () => {
    const client: FakeClient = {
      navigate: vi.fn(() => Promise.reject(new Error('uncontrolled'))),
      focus: vi.fn(),
    }
    const { scope, dispatch } = loadWorker([client])

    await dispatch('notificationclick', tap('/approve/7'))

    expect(scope.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/approve/7`)
  })

  it('never leaves the app origin, whatever the push says', async () => {
    const { scope, dispatch } = loadWorker()

    await dispatch('notificationclick', tap('https://elsewhere.example/phish'))
    await dispatch('notificationclick', tap(null))
    await dispatch('notificationclick', tap(undefined))

    expect(scope.clients.openWindow.mock.calls).toEqual([
      [`${ORIGIN}/`],
      [`${ORIGIN}/`],
      [`${ORIGIN}/`],
    ])
  })

  it('accepts an absolute click_url on its own origin', async () => {
    const { scope, dispatch } = loadWorker()

    await dispatch('notificationclick', tap(`${ORIGIN}/approve/9`))

    expect(scope.clients.openWindow).toHaveBeenCalledWith(`${ORIGIN}/approve/9`)
  })

  it('shows every push, carrying the click_url for the tap', async () => {
    const { scope, dispatch } = loadWorker()

    await dispatch(
      'push',
      pushOf({ title: 'Approval needed', body: 'A7 waits', click_url: '/approve/7' }),
    )

    expect(scope.registration.showNotification).toHaveBeenCalledWith(
      'Approval needed',
      expect.objectContaining({ body: 'A7 waits', data: { click_url: '/approve/7' } }),
    )
  })

  it('still shows a notification when the payload is empty or unreadable', async () => {
    const { scope, dispatch } = loadWorker()

    await dispatch('push', { data: null })
    await dispatch('push', {
      data: {
        json: () => {
          throw new SyntaxError('not json')
        },
      },
    })

    expect(scope.registration.showNotification).toHaveBeenCalledTimes(2)
    expect(scope.registration.showNotification.mock.calls.map(([title]) => title)).toEqual([
      'labhq',
      'labhq',
    ])
  })

  it('takes control of open pages as soon as it is installed', async () => {
    const { scope, dispatch } = loadWorker()

    await dispatch('install', {})
    await dispatch('activate', {})

    expect(scope.skipWaiting).toHaveBeenCalled()
    expect(scope.clients.claim).toHaveBeenCalled()
  })
})
