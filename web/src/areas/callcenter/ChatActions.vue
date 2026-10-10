<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, type RouteLocationRaw } from 'vue-router'

import { api, type components } from '@/api'
import ApprovalActions from '@/areas/approvals/ApprovalActions.vue'
import type { Approval } from '@/areas/approvals/decide'
import { Button } from '@/ui'

type Action = components['schemas']['ChatAction']

// The buttons a CEO message ends with. A button only points: `show` goes to the page, and
// `approve`/`reject` open the approval's own confirmation (a tap, or a passkey when heavy).
defineProps<{ actions: Action[] }>()
const emit = defineEmits<{ navigated: [] }>()

const { t } = useI18n()
const router = useRouter()

// Where `show` goes, by what it names. A new kind of target is one entry.
const SHOW: Record<string, RouteLocationRaw> = {
  report: { name: 'today' },
  approval: { name: 'approvals' },
  meeting: { name: 'meetings' },
  task: { name: 'projects' },
  project: { name: 'projects' },
}

const approval = ref<Approval | null>(null)
const failed = ref(false)

async function run(action: Action): Promise<void> {
  failed.value = false
  if (action.verb === 'show') {
    await router.push(SHOW[action.target_kind] ?? { name: 'today' })
    emit('navigated')
    return
  }
  try {
    const { data } = await api.GET('/api/approvals/{approval_id}', {
      params: { path: { approval_id: action.target_id } },
    })
    if (data) approval.value = data
    else failed.value = true
  } catch {
    failed.value = true
  }
}
</script>

<template>
  <div class="mt-3 flex flex-col gap-2" data-testid="chat-actions">
    <div class="flex flex-wrap gap-2">
      <Button
        v-for="action in actions"
        :key="`${action.verb}-${action.target_kind}-${action.target_id}`"
        size="sm"
        :variant="action.verb === 'approve' ? 'default' : 'outline'"
        :data-testid="`chat-action-${action.verb}`"
        @click="run(action)"
      >
        {{ t(`callcenter.action.${action.verb}`, { id: action.target_id }) }}
      </Button>
    </div>
    <p v-if="failed" role="alert" class="text-sm text-status-failed">
      {{ t('callcenter.errors.approvalGone') }}
    </p>
    <ApprovalActions
      v-if="approval"
      :approval="approval"
      @decided="approval = $event"
      @stale="approval = null"
    />
  </div>
</template>
