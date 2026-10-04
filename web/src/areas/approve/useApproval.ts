import { ref } from 'vue'

import type { Approval } from '@/areas/approvals/decide'
import { authClient } from '@/auth/client'

export type Loaded = 'idle' | 'loading' | 'ready' | 'unknown' | 'failed'

/** One approval by id, for the phone page. `unknown` means the server has no such approval. */
export function useApproval(id: number) {
  const approval = ref<Approval | null>(null)
  const status = ref<Loaded>('idle')

  async function load(): Promise<void> {
    status.value = 'loading'
    try {
      const { data, response } = await authClient().GET('/api/approvals/{approval_id}', {
        params: { path: { approval_id: id } },
      })
      if (data !== undefined) {
        approval.value = data
        status.value = 'ready'
      } else {
        status.value = response.status === 404 ? 'unknown' : 'failed'
      }
    } catch {
      status.value = 'failed'
    }
  }

  function settle(decided: Approval): void {
    approval.value = decided
  }

  return { approval, status, load, settle }
}
