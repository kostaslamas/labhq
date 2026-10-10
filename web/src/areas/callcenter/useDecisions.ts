import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, type components } from '@/api'
import { useLiveTopic } from '@/live'

import type { PinKind } from './store'

export type Decided = components['schemas']['Decided']

// One list for every card on the page: what each ended room decided about a proposal.
export const useDecisions = defineStore('decisions', () => {
  const items = ref<Decided[]>([])

  async function load(): Promise<void> {
    try {
      const { data } = await api.GET('/api/callcenter/decisions')
      if (Array.isArray(data)) items.value = data
    } catch {
      // The card reads the same without it; the next change retries.
    }
  }

  function about(kind: PinKind, id: number): Decided[] {
    return items.value.filter((item) => item.pinned_kind === kind && item.pinned_id === id)
  }

  void load()
  useLiveTopic('meetings', load)
  useLiveTopic('approvals', load)

  return { items, load, about }
})
