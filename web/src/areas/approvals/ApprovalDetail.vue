<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { StatusBadge } from '@/status'
import { uiState } from '@/api'
import DecidedLine from '@/areas/callcenter/DecidedLine.vue'
import DiscussButton from '@/areas/callcenter/DiscussButton.vue'
import { Mono } from '@/ui'

import ApprovalActions from './ApprovalActions.vue'
import type { Approval } from './decide'
import { useLabels } from './useLabels'

defineProps<{ approval: Approval }>()
const emit = defineEmits<{ decided: [approval: Approval]; stale: [] }>()

const { t, locale } = useI18n()
const { typeLabel, confirmationLabel } = useLabels()

function when(instant: string): string {
  // An instant from the API is UTC; show it in the viewer's own zone and language.
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}
</script>

<template>
  <article
    class="glass flex min-w-0 flex-col gap-5 rounded-xl border border-line p-5"
    :aria-label="typeLabel(approval.type)"
    data-testid="approval-detail"
  >
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 class="text-lg font-medium">{{ typeLabel(approval.type) }}</h2>
        <Mono class="text-xs text-muted">A{{ approval.id }} · {{ approval.type }}</Mono>
      </div>
      <StatusBadge :state="uiState('approval_status', approval.status)" />
    </header>

    <dl class="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      <dt class="text-muted">{{ t('approvals.fields.risk') }}</dt>
      <dd>{{ t(`approvals.risk.${approval.risk_class}`) }}</dd>
      <template v-if="approval.project">
        <dt class="text-muted">{{ t('approvals.fields.project') }}</dt>
        <dd>{{ approval.project.name }}</dd>
      </template>
      <template v-if="approval.task">
        <dt class="text-muted">{{ t('approvals.fields.task') }}</dt>
        <dd>{{ approval.task.title }}</dd>
      </template>
      <template v-if="approval.branch">
        <dt class="text-muted">{{ t('approvals.fields.branch') }}</dt>
        <dd>
          <Mono class="break-all">{{ approval.branch }}</Mono>
        </dd>
      </template>
      <template v-if="approval.remote">
        <dt class="text-muted">{{ t('approvals.fields.remote') }}</dt>
        <dd>
          <Mono class="break-all">{{ approval.remote }}</Mono>
        </dd>
      </template>
      <template v-if="approval.requester">
        <dt class="text-muted">{{ t('approvals.fields.requester') }}</dt>
        <dd>{{ approval.requester.title }}</dd>
      </template>
      <dt class="text-muted">{{ t('approvals.fields.requested') }}</dt>
      <dd>{{ when(approval.created_at) }}</dd>
    </dl>

    <section class="flex flex-col gap-2">
      <h3 class="text-sm font-medium text-muted">{{ t('approvals.fields.payload') }}</h3>
      <pre
        class="overflow-x-auto rounded-md bg-surface-raised p-3 font-mono text-xs"
        data-testid="approval-payload"
        >{{ JSON.stringify(approval.payload, null, 2) }}</pre>
    </section>

    <DecidedLine :id="approval.id" kind="approval" />
    <div v-if="approval.status === 'pending'" class="flex">
      <DiscussButton
        :id="approval.id"
        kind="approval"
        :project-id="approval.project?.id ?? null"
        :options="['approve', 'reject', 'show']"
      />
    </div>

    <ApprovalActions
      :approval="approval"
      @decided="emit('decided', $event)"
      @stale="emit('stale')"
    />

    <!-- Not pending: say who or what settled it, from what is stored; offer no action. -->
    <section
      v-if="approval.status !== 'pending'"
      class="flex flex-col gap-2"
      data-testid="decision"
    >
      <h3 class="text-sm font-medium text-muted">{{ t('approvals.decided.title') }}</h3>
      <dl class="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        <dt class="text-muted">{{ t('approvals.decided.by') }}</dt>
        <dd data-testid="decided-by">
          <Mono v-if="approval.decided_by" class="break-all">{{ approval.decided_by }}</Mono>
          <template v-else>{{ t('approvals.decider.unknown') }}</template>
        </dd>
        <template v-if="approval.confirmation_kind">
          <dt class="text-muted">{{ t('approvals.decided.how') }}</dt>
          <dd data-testid="decided-how">{{ confirmationLabel(approval.confirmation_kind) }}</dd>
        </template>
        <template v-if="approval.decided_at">
          <dt class="text-muted">{{ t('approvals.decided.at') }}</dt>
          <dd>{{ when(approval.decided_at) }}</dd>
        </template>
        <template v-if="approval.decision_note">
          <dt class="text-muted">{{ t('approvals.decided.note') }}</dt>
          <dd>{{ approval.decision_note }}</dd>
        </template>
      </dl>
      <pre
        v-if="approval.execution"
        class="overflow-x-auto rounded-md bg-surface-raised p-3 font-mono text-xs"
        data-testid="approval-execution"
        >{{ JSON.stringify(approval.execution, null, 2) }}</pre>
    </section>
  </article>
</template>
