// labhq service worker: shows each Web Push and opens its click_url when it is tapped.
//
// It is plain JavaScript served as-is from the site root, so its scope is the whole app. It has
// no cache and no fetch handler: the app is only ever used online, and a stale shell would
// outlive the API it talks to. `src/push/worker.spec.ts` loads this file with a fake worker
// scope, so every handler below takes what it needs as arguments.

const DEFAULT_TITLE = 'labhq'
const ICON = '/icon-192.png'

/** The payload the server sends: {title, body, click_url}. Anything else still shows something. */
function readPayload(event) {
  try {
    const data = event.data ? event.data.json() : {}
    return {
      title: typeof data.title === 'string' && data.title ? data.title : DEFAULT_TITLE,
      body: typeof data.body === 'string' ? data.body : '',
      clickUrl: typeof data.click_url === 'string' ? data.click_url : null,
    }
  } catch {
    return { title: DEFAULT_TITLE, body: '', clickUrl: null }
  }
}

/** Same-origin only: a push must never be able to send the owner to another site. */
function targetOf(clickUrl, origin) {
  try {
    const url = new URL(clickUrl ?? '/', origin)
    return url.origin === origin ? url.href : `${origin}/`
  } catch {
    return `${origin}/`
  }
}

/** iOS and Chrome both require a visible notification for every push, so always show one. */
function onPush(event, registration) {
  const { title, body, clickUrl } = readPayload(event)
  event.waitUntil(
    registration.showNotification(title, {
      body,
      icon: ICON,
      // Two pushes for the same page replace each other instead of piling up.
      tag: clickUrl ?? title,
      data: { click_url: clickUrl },
    }),
  )
}

async function focusOrOpen(clients, href) {
  const windows = await clients.matchAll({ type: 'window', includeUncontrolled: true })
  for (const client of windows) {
    try {
      // A window of the installed app is reused: a second one would open outside the app.
      await client.navigate(href)
      return await client.focus()
    } catch {
      // This client cannot be navigated; try the next, then open a new window.
    }
  }
  return clients.openWindow(href)
}

function onNotificationClick(event, clients, origin) {
  event.notification.close()
  const href = targetOf(event.notification.data?.click_url, origin)
  event.waitUntil(focusOrOpen(clients, href))
}

function install(scope) {
  scope.addEventListener('install', () => scope.skipWaiting())
  scope.addEventListener('activate', (event) => event.waitUntil(scope.clients.claim()))
  scope.addEventListener('push', (event) => onPush(event, scope.registration))
  scope.addEventListener('notificationclick', (event) =>
    onNotificationClick(event, scope.clients, scope.location.origin),
  )
}

install(self)
