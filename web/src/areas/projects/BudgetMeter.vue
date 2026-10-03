<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { components } from '@/api'
import { formatMicros } from '@/format'
import { StatusBadge } from '@/status'
import { cn, Mono } from '@/ui'

import { budgetStates } from './budgetState'

type Budget = components['schemas']['Budget']

const props = defineProps<{ budget: Budget }>()
const { t } = useI18n()

const verdict = computed(() => budgetStates[props.budget.state])
// The server divides; the bar only clamps a whole percent.
const width = computed(() => Math.min(props.budget.used_percent ?? 0, 100))
const fill = computed(() => {
  switch (props.budget.state) {
    case 'stop':
      return 'bg-status-blocked'
    case 'warn':
      return 'bg-status-waiting'
    default:
      return 'bg-status-working'
  }
})
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5" :data-budget-state="budget.state">
    <div class="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
      <span data-testid="budget-amounts">
        <Mono data-testid="budget-spent">{{ formatMicros(budget.spent_micros) }}</Mono>
        <template v-if="budget.budget_micros !== null">
          <span class="text-muted"> {{ t('projects.budget.of') }} </span>
          <Mono data-testid="budget-limit">{{ formatMicros(budget.budget_micros) }}</Mono>
        </template>
        <span v-else class="text-muted"> · {{ t('projects.budget.noLimit') }}</span>
      </span>
      <Mono v-if="budget.used_percent !== null" class="text-muted" data-testid="budget-percent">
        {{ budget.used_percent }}%
      </Mono>
    </div>
    <div
      v-if="budget.budget_micros !== null"
      class="h-1.5 overflow-hidden rounded-full bg-line"
      role="progressbar"
      :aria-valuenow="width"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="t('projects.budget.label')"
    >
      <div :class="cn('h-full rounded-full', fill)" :style="{ width: `${width}%` }" />
    </div>
    <p v-if="verdict.state" class="flex flex-wrap items-center gap-2 text-xs">
      <StatusBadge :state="verdict.state" data-testid="budget-badge" />
      <span class="text-muted" data-testid="budget-warning">{{ t(verdict.labelKey) }}</span>
    </p>
  </div>
</template>
