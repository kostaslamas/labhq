import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FakeSocket } from './__fixtures__/socket'
import { LIVE_DEFAULTS, LiveConnection, liveUrl, type LiveState } from './connection'

function connect(states: LiveState[] = []): LiveConnection {
  return new LiveConnection({
    ...LIVE_DEFAULTS,
    url: 'ws://labhq.test/api/live',
    createSocket: (url) => new FakeSocket(url),
    // No jitter: the delay is exactly the upper half of the ceiling, i.e. the ceiling.
    random: () => 1,
    onStateChange: (state) => states.push(state),
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.all = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('LiveConnection', () => {
  it('refetches every subscribed topic after a reconnect', () => {
    const live = connect()
    const approvals = vi.fn()
    const tasks = vi.fn()
    const runs = vi.fn()
    live.subscribe('approvals', approvals)
    live.subscribe('tasks', tasks)
    live.subscribe('runs', runs)
    FakeSocket.latest().open()
    expect(approvals).not.toHaveBeenCalled()

    FakeSocket.latest().drop()
    vi.advanceTimersByTime(LIVE_DEFAULTS.initialBackoffMs)
    expect(FakeSocket.all).toHaveLength(2)
    FakeSocket.latest().open()

    expect(approvals).toHaveBeenCalledOnce()
    expect(tasks).toHaveBeenCalledOnce()
    expect(runs).toHaveBeenCalledOnce()
  })

  it('refetches after the first connection succeeds only on a retry', () => {
    const live = connect()
    const approvals = vi.fn()
    live.subscribe('approvals', approvals)
    FakeSocket.latest().drop()
    vi.advanceTimersByTime(LIVE_DEFAULTS.initialBackoffMs)
    FakeSocket.latest().open()
    expect(approvals).toHaveBeenCalledOnce()
  })

  it('refetches only the topic that moved, once per watermark', () => {
    const live = connect()
    const approvals = vi.fn()
    const tasks = vi.fn()
    live.subscribe('approvals', approvals)
    live.subscribe('tasks', tasks)
    const socket = FakeSocket.latest()
    socket.open()

    socket.invalidate('approvals', '7|7')
    socket.invalidate('approvals', '7|7')
    socket.send({ type: 'heartbeat' })
    socket.invalidate('meetings', '1')

    expect(approvals).toHaveBeenCalledOnce()
    expect(tasks).not.toHaveBeenCalled()
    socket.invalidate('approvals', '8|8')
    expect(approvals).toHaveBeenCalledTimes(2)
  })

  it('backs off exponentially up to a ceiling and resets after a success', () => {
    const states: LiveState[] = []
    const live = connect(states)
    live.subscribe('tasks', vi.fn())
    const delays: number[] = []
    for (let attempt = 0; attempt < 7; attempt += 1) {
      FakeSocket.latest().drop()
      const before = FakeSocket.all.length
      let waited = 0
      while (FakeSocket.all.length === before) {
        vi.advanceTimersByTime(250)
        waited += 250
      }
      delays.push(waited)
    }
    expect(delays).toEqual([1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000])

    FakeSocket.latest().open()
    FakeSocket.latest().drop()
    const afterSuccess = FakeSocket.all.length
    vi.advanceTimersByTime(LIVE_DEFAULTS.initialBackoffMs)
    expect(FakeSocket.all).toHaveLength(afterSuccess + 1)
    expect(states).toEqual(expect.arrayContaining(['connecting', 'offline', 'open']))
  })

  it('treats a silent socket as dead and reconnects', () => {
    const live = connect()
    const runs = vi.fn()
    live.subscribe('runs', runs)
    const socket = FakeSocket.latest()
    socket.open()
    vi.advanceTimersByTime(LIVE_DEFAULTS.staleAfterMs - 1)
    socket.send({ type: 'heartbeat' })
    vi.advanceTimersByTime(LIVE_DEFAULTS.staleAfterMs - 1)
    expect(socket.closedWith).toBeNull()

    vi.advanceTimersByTime(1)
    expect(socket.closedWith).toBe(4000)
    vi.advanceTimersByTime(LIVE_DEFAULTS.initialBackoffMs)
    FakeSocket.latest().open()
    expect(FakeSocket.all).toHaveLength(2)
    expect(runs).toHaveBeenCalledOnce()
  })

  it('closes the socket when the last subscriber leaves and stops retrying', () => {
    const states: LiveState[] = []
    const live = connect(states)
    const stopTasks = live.subscribe('tasks', vi.fn())
    const stopRuns = live.subscribe('runs', vi.fn())
    const socket = FakeSocket.latest()
    socket.open()

    stopTasks()
    expect(socket.closedWith).toBeNull()
    stopRuns()
    expect(socket.closedWith).toBe(1000)
    expect(live.currentState).toBe('idle')
    socket.drop()
    vi.advanceTimersByTime(LIVE_DEFAULTS.maxBackoffMs)
    expect(FakeSocket.all).toHaveLength(1)
  })

  it('ignores messages it does not understand', () => {
    const live = connect()
    const tasks = vi.fn()
    live.subscribe('tasks', tasks)
    const socket = FakeSocket.latest()
    socket.open()
    socket.onmessage?.(new MessageEvent('message', { data: 'not json' }))
    socket.send({ type: 'invalidate', topic: 'tasks' })
    expect(tasks).not.toHaveBeenCalled()
  })
})

describe('liveUrl', () => {
  it('follows the page scheme, so the tunnel gets wss', () => {
    expect(liveUrl({ protocol: 'https:', host: 'x.trycloudflare.com' })).toBe(
      'wss://x.trycloudflare.com/api/live',
    )
    expect(liveUrl({ protocol: 'http:', host: '127.0.0.1:8787' })).toBe(
      'ws://127.0.0.1:8787/api/live',
    )
  })
})
