import { getCurrentScope, onScopeDispose, readonly, ref } from 'vue'

import { LIVE_DEFAULTS, LiveConnection, liveUrl, type LiveState, type Refetch } from './connection'

const state = ref<LiveState>('idle')
let shared: LiveConnection | null = null

function connection(): LiveConnection {
  shared ??= new LiveConnection({
    ...LIVE_DEFAULTS,
    url: liveUrl(window.location),
    createSocket: (url) => new WebSocket(url),
    random: Math.random,
    onStateChange: (next) => {
      state.value = next
    },
  })
  return shared
}

/** The tab's link to `/api/live`, for a page that shows when updates are paused. */
export const liveState = readonly(state)

/**
 * Call `refetch` whenever `topic` changes on the server, and after every reconnect.
 *
 * The page still fetches once on its own; this only keeps it fresh. The subscription ends
 * with the calling component or effect scope.
 */
export function useLiveTopic(topic: string, refetch: Refetch): () => void {
  const unsubscribe = connection().subscribe(topic, refetch)
  if (getCurrentScope()) onScopeDispose(unsubscribe)
  return unsubscribe
}

/** Tests only: forget the shared connection so the next subscription builds a fresh one. */
export function resetLiveConnection(): void {
  shared = null
  state.value = 'idle'
}
