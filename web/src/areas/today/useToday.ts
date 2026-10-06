import { onMounted, ref } from 'vue'

import { api, type components } from '@/api'
import { useLiveTopic } from '@/live'

export type Today = components['schemas']['Today']

// Every table the page reads (ADR 0006): a change in any of them refetches the whole answer.
// CEO reports are written by CEO runs, so `runs` brings the latest one.
export const TODAY_TOPICS = [
  'approvals',
  'tasks',
  'questions',
  'incidents',
  'costs',
  'runs',
] as const

export function useToday() {
  const today = ref<Today | null>(null)
  const failed = ref(false)

  async function load(): Promise<void> {
    try {
      const { data } = await api.GET('/api/today')
      // Keep the last good answer on screen when a refetch fails.
      if (data) today.value = data
      failed.value = data === undefined
    } catch {
      // The network itself failed; the live connection refetches when it is back.
      failed.value = true
    }
  }

  onMounted(load)
  for (const topic of TODAY_TOPICS) useLiveTopic(topic, load)

  return { today, failed, reload: load }
}
