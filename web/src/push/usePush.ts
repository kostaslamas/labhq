import { onMounted, readonly, ref } from 'vue'

import { authClient } from '@/auth/client'

import {
  pushAvailability,
  readPushFacts,
  type PushAvailability,
  type PushFacts,
} from './environment'
import {
  browserPush,
  currentSubscription,
  PushFailure,
  subscribeDevice,
  unsubscribeDevice,
  type PushBrowser,
  type PushFailureKind,
} from './subscription'

export interface PushDeps {
  facts(): PushFacts
  browser: PushBrowser
}

/** The enable-notifications step: what this device can do, whether it is subscribed, and why not. */
export function usePush(deps: PushDeps = { facts: readPushFacts, browser: browserPush() }) {
  const availability = ref<PushAvailability>(pushAvailability(deps.facts()))
  const subscribed = ref(false)
  const busy = ref(false)
  const failure = ref<PushFailureKind | null>(null)

  async function refresh(): Promise<void> {
    availability.value = pushAvailability(deps.facts())
    if (availability.value !== 'available') return
    try {
      subscribed.value = (await currentSubscription(deps.browser)) !== null
    } catch {
      subscribed.value = false
    }
  }

  async function run(action: () => Promise<void>): Promise<void> {
    busy.value = true
    failure.value = null
    try {
      await action()
    } catch (error) {
      failure.value = error instanceof PushFailure ? error.kind : 'browser'
    } finally {
      busy.value = false
      await refresh()
    }
  }

  const enable = () => run(() => subscribeDevice(authClient(), deps.browser))
  const disable = () => run(() => unsubscribeDevice(authClient(), deps.browser))

  onMounted(refresh)

  return {
    availability: readonly(availability),
    subscribed: readonly(subscribed),
    busy: readonly(busy),
    failure: readonly(failure),
    enable,
    disable,
  }
}
