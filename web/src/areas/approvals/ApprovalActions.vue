<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useFailureMessage } from '@/areas/auth/useFailureMessage'
import { useStepUp } from '@/auth'
import { Button } from '@/ui'

import { submitDecision, type Approval, type Decision, type DecisionFailure } from './decide'

// The approve and reject buttons of one approval. The phone approval page reuses this as is.
const props = defineProps<{ approval: Approval }>()
const emit = defineEmits<{ decided: [approval: Approval]; stale: [] }>()

const { t } = useI18n()
const stepUp = useStepUp()
const passkeyMessage = useFailureMessage()

const MESSAGE_KEYS: Record<DecisionFailure, string> = {
  refused: 'approvals.errors.refused',
  step_up_required: 'approvals.errors.step_up_required',
  already_decided: 'approvals.errors.already_decided',
  not_allowed: 'approvals.errors.not_allowed',
  failed: 'approvals.errors.failed',
  network: 'approvals.errors.network',
}

const busy = ref(false)
const failure = ref<DecisionFailure | null>(null)
// One key per intent, kept across a lost connection so a retry cannot decide twice.
const pendingKey = ref<{ decision: Decision; key: string } | null>(null)

const actionable = computed(() => props.approval.status === 'pending')
const heavy = computed(() => props.approval.risk_class === 'heavy')
const approveLabel = computed(() =>
  t(heavy.value ? 'approvals.actions.approve_heavy' : 'approvals.actions.approve'),
)
const message = computed(() => {
  if (stepUp.failure.value) {
    return `${passkeyMessage(stepUp.failure.value)} ${t('approvals.errors.still_pending')}`
  }
  return failure.value ? t(MESSAGE_KEYS[failure.value]) : ''
})

function keyFor(decision: Decision): string {
  if (pendingKey.value?.decision !== decision) {
    pendingKey.value = { decision, key: crypto.randomUUID() }
  }
  return pendingKey.value.key
}

async function decide(decision: Decision): Promise<void> {
  if (busy.value || !actionable.value) return
  busy.value = true
  failure.value = null
  try {
    let credential
    if (decision === 'approve' && heavy.value) {
      // Asked now, when the button is pressed: the assertion is single use and short lived.
      credential = (await stepUp.requestAssertion(`approval:${props.approval.id}`)) ?? undefined
      if (credential === undefined) return
    }
    const result = await submitDecision(props.approval.id, decision, keyFor(decision), credential)
    if (result.ok) {
      pendingKey.value = null
      emit('decided', result.approval)
      return
    }
    failure.value = result.failure
    // Anything but a lost connection is a final answer for this intent.
    if (result.failure !== 'network') pendingKey.value = null
    if (result.failure === 'already_decided') emit('stale')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="actionable" class="flex flex-col gap-3" data-testid="approval-actions">
    <p class="text-sm text-muted">
      {{ heavy ? t('approvals.actions.heavy_hint') : t('approvals.actions.light_hint') }}
    </p>
    <div class="flex flex-wrap gap-3">
      <Button :disabled="busy" data-testid="approve" @click="decide('approve')">
        {{ busy ? t('approvals.actions.working') : approveLabel }}
      </Button>
      <Button variant="outline" :disabled="busy" data-testid="reject" @click="decide('reject')">
        {{ t('approvals.actions.reject') }}
      </Button>
    </div>
    <p v-if="message" role="alert" class="text-sm text-status-failed" data-testid="decision-error">
      {{ message }}
    </p>
  </div>
</template>
