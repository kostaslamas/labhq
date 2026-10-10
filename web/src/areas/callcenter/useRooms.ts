import { computed, ref, watch } from 'vue'

import { api, isErrorEnvelope, type components } from '@/api'
import { useLiveTopic } from '@/live'

export type Room = components['schemas']['RoomItem']
export type RoomDetail = components['schemas']['MeetingDetail']

const OPEN = new Set(['requested', 'running'])

// The decision rooms and the one the widget shows. Updates arrive by live topic.
export function useRooms() {
  const rooms = ref<Room[]>([])
  const detail = ref<RoomDetail | null>(null)
  const failure = ref('')
  const busy = ref(false)

  // The room that is not over; otherwise the latest one, so its outcome stays readable.
  const current = computed<Room | null>(
    () => rooms.value.find((room) => OPEN.has(room.status)) ?? rooms.value[0] ?? null,
  )
  const offered = computed(() => rooms.value.filter((room) => room.status === 'requested'))

  async function loadDetail(): Promise<void> {
    const room = current.value
    if (!room || room.status === 'requested') {
      detail.value = null
      return
    }
    const { data } = await api.GET('/api/meetings/{meeting_id}', {
      params: { path: { meeting_id: room.id } },
    })
    if (data) detail.value = data
  }

  async function load(): Promise<void> {
    try {
      const { data } = await api.GET('/api/callcenter/rooms')
      if (Array.isArray(data)) rooms.value = data
      await loadDetail()
    } catch {
      // The widget keeps what it has; the next change retries.
    }
  }

  async function act(run: () => Promise<{ error?: unknown }>): Promise<boolean> {
    if (busy.value) return false
    busy.value = true
    failure.value = ''
    try {
      const { error } = await run()
      if (error === undefined) return true
      failure.value = isErrorEnvelope(error) ? error.error.message : 'callcenter.errors.roomFailed'
      return false
    } catch {
      failure.value = 'callcenter.errors.roomFailed'
      return false
    } finally {
      busy.value = false
      await load()
    }
  }

  const path = (id: number) => ({ params: { path: { room_id: id } } })

  const start = (id: number) =>
    act(() => api.POST('/api/callcenter/rooms/{room_id}/start', path(id)))
  const decline = (id: number) =>
    act(() => api.POST('/api/callcenter/rooms/{room_id}/decline', path(id)))
  const close = (id: number) =>
    act(() => api.POST('/api/callcenter/rooms/{room_id}/close', path(id)))
  const say = (id: number, text: string) =>
    act(() =>
      api.POST('/api/callcenter/rooms/{room_id}/messages', {
        ...path(id),
        body: { text },
        // One key per message: a retry after a lost connection records it once.
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      }),
    )

  watch(() => current.value?.id, loadDetail)
  void load()
  useLiveTopic('meetings', load)
  useLiveTopic('approvals', load)

  return { rooms, current, offered, detail, failure, busy, load, start, decline, close, say }
}
