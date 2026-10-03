import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { FakeSocket } from './__fixtures__/socket'
import { LIVE_DEFAULTS } from './connection'
import { liveState, resetLiveConnection, useLiveTopic } from './useLiveTopic'

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.all = []
  vi.stubGlobal('WebSocket', FakeSocket)
  resetLiveConnection()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useLiveTopic', () => {
  it('shares one socket and refetches every subscribed topic after a reconnect', () => {
    const approvals = vi.fn()
    const tasks = vi.fn()
    const scope = effectScope()
    scope.run(() => {
      useLiveTopic('approvals', approvals)
      useLiveTopic('tasks', tasks)
    })
    expect(FakeSocket.all).toHaveLength(1)
    expect(FakeSocket.latest().url).toBe(`ws://${window.location.host}/api/live`)
    FakeSocket.latest().open()
    expect(liveState.value).toBe('open')

    FakeSocket.latest().drop()
    expect(liveState.value).toBe('offline')
    vi.advanceTimersByTime(LIVE_DEFAULTS.maxBackoffMs)
    FakeSocket.latest().open()

    expect(approvals).toHaveBeenCalledOnce()
    expect(tasks).toHaveBeenCalledOnce()
    scope.stop()
  })

  it('unsubscribes when the component scope ends', () => {
    const scope = effectScope()
    scope.run(() => useLiveTopic('runs', vi.fn()))
    const socket = FakeSocket.latest()
    socket.open()
    scope.stop()
    expect(socket.closedWith).toBe(1000)
    expect(liveState.value).toBe('idle')
  })
})
