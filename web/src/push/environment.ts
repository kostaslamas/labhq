// What this browser can do about Web Push, decided from plain facts so a test can state them.

export type PushAvailability =
  // No service worker, push or notifications here (or no secure context).
  | 'unsupported'
  // iOS only delivers Web Push to an app added to the Home Screen, never to a Safari tab.
  | 'needs_install'
  // The person blocked notifications for this address; only browser settings can undo it.
  | 'denied'
  | 'available'

export interface PushFacts {
  userAgent: string
  platform: string
  maxTouchPoints: number
  /** The page runs as an installed app (display-mode: standalone, or iOS `navigator.standalone`). */
  standalone: boolean
  secureContext: boolean
  hasServiceWorker: boolean
  hasPushManager: boolean
  permission: NotificationPermission | 'unsupported'
}

export function isIos(
  facts: Pick<PushFacts, 'userAgent' | 'platform' | 'maxTouchPoints'>,
): boolean {
  if (/iPhone|iPad|iPod/.test(facts.userAgent)) return true
  // iPadOS reports a Mac; only a touch screen tells them apart.
  return facts.platform === 'MacIntel' && facts.maxTouchPoints > 1
}

export function pushAvailability(facts: PushFacts): PushAvailability {
  // Checked before capabilities: Safari on iOS hides PushManager outside the Home Screen, and
  // "unsupported" would send the person away from the one thing that fixes it.
  if (isIos(facts) && !facts.standalone && facts.secureContext) return 'needs_install'
  if (
    !facts.secureContext ||
    !facts.hasServiceWorker ||
    !facts.hasPushManager ||
    facts.permission === 'unsupported'
  ) {
    return 'unsupported'
  }
  return facts.permission === 'denied' ? 'denied' : 'available'
}

interface IosNavigator extends Navigator {
  standalone?: boolean
}

export function readPushFacts(): PushFacts {
  const nav = navigator as IosNavigator
  return {
    userAgent: nav.userAgent,
    platform: nav.platform,
    maxTouchPoints: nav.maxTouchPoints,
    standalone:
      nav.standalone === true || window.matchMedia?.('(display-mode: standalone)').matches === true,
    secureContext: window.isSecureContext,
    hasServiceWorker: 'serviceWorker' in nav,
    hasPushManager: 'PushManager' in window,
    permission: 'Notification' in window ? Notification.permission : 'unsupported',
  }
}
