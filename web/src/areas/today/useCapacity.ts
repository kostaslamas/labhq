import { onMounted, onUnmounted, ref } from 'vue'

import { api, type components } from '@/api'
import { useLiveTopic } from '@/live'

export type RunCapacity = components['schemas']['RunCapacity']

// Free memory moves without any table changing, so the card also re-reads on a timer.
export const CAPACITY_REFRESH_MS = 30_000

export function useCapacity() {
  const capacity = ref<RunCapacity | null>(null)

  async function load(): Promise<void> {
    try {
      const { data } = await api.GET('/api/capacity')
      // A failed refetch keeps the last reading; the card is never worth an error banner.
      if (data) capacity.value = data
    } catch {
      // The live connection and the timer try again.
    }
  }

  let timer: ReturnType<typeof setInterval> | undefined
  onMounted(() => {
    void load()
    timer = setInterval(load, CAPACITY_REFRESH_MS)
  })
  onUnmounted(() => clearInterval(timer))
  useLiveTopic('runs', load)

  return { capacity }
}
