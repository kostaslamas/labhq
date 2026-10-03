import { onMounted, ref } from 'vue'

import { authClient } from '@/auth/client'
import { useLiveTopic } from '@/live'

import type { Approval } from './decide'

/** The approvals the page shows, kept fresh by the `approvals` live topic. */
export function useApprovals() {
  const items = ref<Approval[]>([])
  const loading = ref(true)
  const failed = ref(false)

  async function refresh(): Promise<void> {
    try {
      const { data } = await authClient().GET('/api/approvals', { params: { query: {} } })
      failed.value = data === undefined
      if (data !== undefined) items.value = data.items
    } catch {
      failed.value = true
    } finally {
      loading.value = false
    }
  }

  onMounted(refresh)
  useLiveTopic('approvals', refresh)

  return { items, loading, failed, refresh }
}
