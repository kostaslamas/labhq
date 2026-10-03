// Subscribe this browser to Web Push and tell the server, or undo both.
//
// The endpoint and keys go to the server and nowhere else: they are not logged, stored in the
// page, or shown.
import type { ApiClient } from '@/api'

export type PushFailureKind = 'permission' | 'sign_in' | 'server' | 'browser'

export class PushFailure extends Error {
  readonly kind: PushFailureKind

  constructor(kind: PushFailureKind) {
    super(kind)
    this.kind = kind
  }
}

/** The pieces of the browser a subscription touches, so a test can stand in for them. */
export interface PushBrowser {
  requestPermission(): Promise<NotificationPermission>
  registration(): Promise<ServiceWorkerRegistration>
}

export function browserPush(): PushBrowser {
  return {
    requestPermission: () => Notification.requestPermission(),
    registration: () => navigator.serviceWorker.ready,
  }
}

// `applicationServerKey` wants the bytes of the VAPID public key, which the server sends as
// base64url.
export function keyBytes(base64Url: string): Uint8Array<ArrayBuffer> {
  const padded = base64Url
    .replace(/-/g, '+')
    .replace(/_/g, '/')
    .padEnd(Math.ceil(base64Url.length / 4) * 4, '=')
  const raw = atob(padded)
  return Uint8Array.from(raw, (character) => character.charCodeAt(0))
}

export async function currentSubscription(browser: PushBrowser): Promise<PushSubscription | null> {
  return (await browser.registration()).pushManager.getSubscription()
}

export async function subscribeDevice(client: ApiClient, browser: PushBrowser): Promise<void> {
  const { data: status, response } = await client.GET('/api/push/status')
  if (!status) throw new PushFailure(response?.status === 401 ? 'sign_in' : 'server')
  // Asked from the button press: iOS and Safari only prompt after a user gesture.
  if ((await browser.requestPermission()) !== 'granted') throw new PushFailure('permission')
  const registration = await browser.registration()
  let subscription: PushSubscription
  try {
    subscription =
      (await registration.pushManager.getSubscription()) ??
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyBytes(status.public_key),
      }))
  } catch {
    throw new PushFailure('browser')
  }
  const { keys } = subscription.toJSON()
  if (!keys?.p256dh || !keys.auth) throw new PushFailure('browser')
  const { error, response: saved } = await client.POST('/api/push/subscriptions', {
    body: { endpoint: subscription.endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } },
  })
  if (error !== undefined) throw new PushFailure(saved.status === 401 ? 'sign_in' : 'server')
}

export async function unsubscribeDevice(client: ApiClient, browser: PushBrowser): Promise<void> {
  const subscription = await currentSubscription(browser)
  if (!subscription) return
  const { error, response } = await client.POST('/api/push/subscriptions/remove', {
    body: { endpoint: subscription.endpoint },
  })
  if (error !== undefined) throw new PushFailure(response.status === 401 ? 'sign_in' : 'server')
  await subscription.unsubscribe()
}
