// One WebSocket to `/api/live` for the whole tab (ADR 0006). Messages are invalidations:
// the server says a topic moved and each subscriber refetches through the normal API.

export type Refetch = () => unknown
export type LiveState = 'idle' | 'connecting' | 'open' | 'offline'

export interface SocketLike {
  onopen: ((event: Event) => unknown) | null
  onmessage: ((event: MessageEvent) => unknown) | null
  onclose: ((event: CloseEvent) => unknown) | null
  onerror: ((event: Event) => unknown) | null
  close(code?: number, reason?: string): void
}

export interface LiveOptions {
  url: string
  createSocket: (url: string) => SocketLike
  // Backoff before reconnect attempt n (from 0) is min(initial * 2^n, max), with jitter.
  initialBackoffMs: number
  maxBackoffMs: number
  // The server sends a heartbeat every 20 s; this long without any message is a dead link
  // that the browser has not noticed (a sleeping laptop, a proxy that dropped the socket).
  staleAfterMs: number
  random: () => number
  onStateChange?: (state: LiveState) => void
}

export const LIVE_DEFAULTS = {
  initialBackoffMs: 1_000,
  maxBackoffMs: 30_000,
  staleAfterMs: 45_000,
} as const

interface Invalidation {
  type: 'invalidate'
  topic: string
  watermark: string
}

function isInvalidation(message: unknown): message is Invalidation {
  if (typeof message !== 'object' || message === null) return false
  const { type, topic, watermark } = message as Record<string, unknown>
  return type === 'invalidate' && typeof topic === 'string' && typeof watermark === 'string'
}

export function liveUrl(location: Pick<Location, 'protocol' | 'host'>): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/api/live`
}

export class LiveConnection {
  private readonly subscribers = new Map<string, Set<Refetch>>()
  private readonly seen = new Map<string, string>()
  private socket: SocketLike | null = null
  private attempt = 0
  private hasOpened = false
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private staleTimer: ReturnType<typeof setTimeout> | null = null
  private state: LiveState = 'idle'

  constructor(private readonly options: LiveOptions) {}

  get currentState(): LiveState {
    return this.state
  }

  subscribe(topic: string, refetch: Refetch): () => void {
    const refetches = this.subscribers.get(topic) ?? new Set<Refetch>()
    refetches.add(refetch)
    this.subscribers.set(topic, refetches)
    if (this.state === 'idle') this.connect()
    return () => this.unsubscribe(topic, refetch)
  }

  private unsubscribe(topic: string, refetch: Refetch): void {
    const refetches = this.subscribers.get(topic)
    refetches?.delete(refetch)
    if (refetches?.size === 0) this.subscribers.delete(topic)
    if (this.subscribers.size === 0) this.stop()
  }

  private connect(): void {
    this.setState('connecting')
    const socket = this.options.createSocket(this.options.url)
    this.socket = socket
    socket.onopen = () => this.opened()
    socket.onmessage = (event) => this.received(event)
    socket.onclose = () => this.lost(socket)
    // An error is always followed by a close; reconnecting happens there, once.
    socket.onerror = null
  }

  private opened(): void {
    const reconnected = this.hasOpened || this.attempt > 0
    this.hasOpened = true
    this.attempt = 0
    this.setState('open')
    this.armStaleTimer()
    // Whatever changed while offline was never announced: refetch everything once.
    if (reconnected) this.refetchAll()
  }

  private received(event: MessageEvent): void {
    this.armStaleTimer()
    let message: unknown
    try {
      message = JSON.parse(String(event.data))
    } catch {
      return
    }
    if (!isInvalidation(message)) return
    if (this.seen.get(message.topic) === message.watermark) return
    this.seen.set(message.topic, message.watermark)
    this.refetch(message.topic)
  }

  private lost(socket: SocketLike): void {
    if (socket !== this.socket) return
    this.socket = null
    this.clearStaleTimer()
    if (this.subscribers.size === 0) return
    this.setState('offline')
    const ceiling = Math.min(
      this.options.initialBackoffMs * 2 ** this.attempt,
      this.options.maxBackoffMs,
    )
    this.attempt += 1
    // Full jitter, so tabs that lost the server together do not return in lockstep.
    const delay = ceiling / 2 + (this.options.random() * ceiling) / 2
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  private refetch(topic: string): void {
    for (const refetch of this.subscribers.get(topic) ?? []) void refetch()
  }

  private refetchAll(): void {
    for (const topic of this.subscribers.keys()) this.refetch(topic)
  }

  private armStaleTimer(): void {
    this.clearStaleTimer()
    this.staleTimer = setTimeout(() => {
      // Closing triggers `onclose` in a browser; act now in case it never comes.
      const socket = this.socket
      socket?.close(4000, 'stale')
      if (socket) this.lost(socket)
    }, this.options.staleAfterMs)
  }

  private clearStaleTimer(): void {
    if (this.staleTimer !== null) clearTimeout(this.staleTimer)
    this.staleTimer = null
  }

  private stop(): void {
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.clearStaleTimer()
    const socket = this.socket
    this.socket = null
    socket?.close(1000, 'no subscribers')
    this.attempt = 0
    this.hasOpened = false
    this.setState('idle')
  }

  private setState(state: LiveState): void {
    if (this.state === state) return
    this.state = state
    this.options.onStateChange?.(state)
  }
}
