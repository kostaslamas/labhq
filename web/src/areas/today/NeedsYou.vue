<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { uiState } from '@/api'
import DiscussButton from '@/areas/callcenter/DiscussButton.vue'
import { formatMicros } from '@/format'
import { StatusBadge } from '@/status'
import { Mono } from '@/ui'

import type { Today } from './useToday'

const props = defineProps<{ needs: Today['needs_you'] }>()
const { t } = useI18n()
const empty = computed(() => props.needs.count === 0)
</script>

<template>
  <section aria-labelledby="needs-you-title" class="flex flex-col gap-3" data-testid="needs-you">
    <h2 id="needs-you-title" class="flex items-center gap-3 text-lg font-semibold">
      {{ t('today.needs.title') }}
      <span
        class="rounded-full border border-line px-2.5 py-0.5 text-sm font-medium"
        data-testid="needs-count"
        >{{ needs.count }}</span
      >
    </h2>
    <p v-if="empty" class="glass rounded-xl border border-line p-4 text-muted">
      {{ t('today.needs.empty') }}
    </p>
    <ul v-else class="glass divide-y divide-line rounded-xl border border-line">
      <li
        v-for="approval in needs.approvals"
        :key="`approval-${approval.id}`"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
        data-testid="need-approval"
      >
        <div class="flex min-w-0 flex-col gap-1">
          <RouterLink :to="{ name: 'approvals' }" class="font-medium hover:underline">
            {{ t('today.needs.approval', { type: approval.type }) }}
            <span v-if="approval.risk_class === 'heavy'" class="text-status-waiting">
              · {{ t('today.needs.heavy') }}
            </span>
          </RouterLink>
          <span class="text-sm text-muted">
            <Mono>#{{ approval.id }}</Mono>
            <template v-if="approval.task_title"> · {{ approval.task_title }}</template>
            <template v-if="approval.project_name">
              ·
              <RouterLink :to="{ name: 'projects' }" class="hover:underline">{{
                approval.project_name
              }}</RouterLink>
            </template>
          </span>
        </div>
        <div class="flex items-center gap-3">
          <DiscussButton
            :id="approval.id"
            kind="approval"
            :project-id="approval.project_id"
            :options="['approve', 'reject', 'show']"
          />
          <StatusBadge :state="uiState('approval_status', approval.status)" />
        </div>
      </li>

      <li
        v-for="question in needs.questions"
        :key="`question-${question.id}`"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
        data-testid="need-question"
      >
        <div class="flex min-w-0 flex-col gap-1">
          <span class="font-medium">{{ question.question }}</span>
          <span class="text-sm text-muted">
            {{ t('today.needs.asked_by', { agent: question.agent_title }) }}
            <template v-if="question.project_id">
              ·
              <RouterLink :to="{ name: 'projects' }" class="hover:underline">{{
                t('today.needs.project')
              }}</RouterLink>
            </template>
          </span>
        </div>
        <StatusBadge :state="uiState('question_status', question.status)" />
      </li>

      <li
        v-for="incident in needs.incidents"
        :key="`incident-${incident.id}`"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
        data-testid="need-incident"
      >
        <div class="flex min-w-0 flex-col gap-1">
          <RouterLink :to="{ name: 'rules' }" class="font-medium hover:underline">{{
            incident.rule_name
          }}</RouterLink>
          <span class="text-sm text-muted">
            {{ t('today.needs.on_host') }} <Mono>{{ incident.host_name }}</Mono>
          </span>
        </div>
        <StatusBadge :state="uiState('incident_status', incident.status)" />
      </li>

      <li
        v-for="warning in needs.budget_warnings"
        :key="`budget-${warning.id}`"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
        data-testid="need-budget"
      >
        <div class="flex min-w-0 flex-col gap-1">
          <span class="font-medium">{{ t('today.needs.budget', { name: warning.name }) }}</span>
          <span class="text-sm text-muted">
            <Mono>{{ formatMicros(warning.spent_micros) }}</Mono>
            {{ t('today.needs.of') }}
            <Mono>{{ formatMicros(warning.budget_micros) }}</Mono>
          </span>
        </div>
        <StatusBadge state="blocked" />
      </li>
    </ul>
  </section>
</template>
