<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { uiState } from '@/api'
import { formatMicros } from '@/format'
import { StatusBadge } from '@/status'
import { Mono } from '@/ui'

import type { Today } from './useToday'

defineProps<{ deliverables: Today['deliverables'] }>()
const { t, locale } = useI18n()

// An instant from the API is UTC; show it in the viewer's own zone and language.
function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}
</script>

<template>
  <section aria-labelledby="delivered-title" class="flex flex-col gap-3" data-testid="delivered">
    <h2 id="delivered-title" class="text-lg font-semibold">{{ t('today.delivered.title') }}</h2>
    <p v-if="deliverables.length === 0" class="glass rounded-xl border border-line p-4 text-muted">
      {{ t('today.delivered.empty') }}
    </p>
    <ul v-else class="glass divide-y divide-line rounded-xl border border-line">
      <li
        v-for="item in deliverables"
        :key="item.task_id"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
        data-testid="deliverable"
      >
        <div class="flex min-w-0 flex-col gap-1">
          <span class="font-medium">{{ item.title }}</span>
          <span class="text-sm text-muted">
            <RouterLink :to="{ name: 'projects' }" class="hover:underline">{{
              item.project_name
            }}</RouterLink>
            · <time :datetime="item.finished_at">{{ when(item.finished_at) }}</time>
          </span>
          <span class="flex flex-wrap gap-x-3 text-sm text-muted">
            <Mono v-if="item.branch" class="break-all">{{ item.branch }}</Mono>
            <span>
              <Mono>{{ item.commit_count }}</Mono>
              {{ t('today.delivered.commits', item.commit_count) }}
            </span>
            <RouterLink
              v-for="approval in item.approvals"
              :key="approval.id"
              :to="{ name: 'approvals' }"
              class="hover:underline"
            >
              {{ t('today.delivered.executed', { type: approval.type }) }}
              <Mono>#{{ approval.id }}</Mono>
            </RouterLink>
          </span>
        </div>
        <div class="flex items-center gap-3">
          <Mono class="text-sm">{{ formatMicros(item.cost_micros) }}</Mono>
          <StatusBadge :state="uiState('task_status', 'done')" />
        </div>
      </li>
    </ul>
  </section>
</template>
