<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { uiState, type components } from '@/api'
import { StatusBadge } from '@/status'
import { Mono } from '@/ui'

import BudgetMeter from './BudgetMeter.vue'
import TaskCounts from './TaskCounts.vue'

type Card = components['schemas']['ProjectCard']

defineProps<{ card: Card }>()
const { t } = useI18n()
</script>

<template>
  <li class="glass flex min-w-0 flex-col gap-4 rounded-xl border border-line p-5">
    <div class="flex items-start justify-between gap-3">
      <h2 class="min-w-0 break-words text-lg font-semibold">
        <RouterLink
          :to="{ name: 'project', params: { id: card.id } }"
          class="hover:underline focus-visible:underline"
          data-testid="project-link"
        >
          {{ card.name }}
        </RouterLink>
      </h2>
      <StatusBadge :state="uiState('project_status', card.status)" />
    </div>

    <RouterLink
      v-if="card.name === 'infra'"
      :to="{ name: 'rules' }"
      class="text-sm text-muted underline hover:text-foreground"
      data-testid="rules-link"
    >
      {{ t('projects.rulesLink') }}
    </RouterLink>

    <p v-if="card.sessions" class="text-sm text-muted" data-testid="session-counts">
      {{
        t('projects.card.sessions', {
          total: card.sessions.total,
          running: card.sessions.running,
          idle: card.sessions.idle,
        })
      }}<template v-if="card.sessions.waiting > 0">{{
        t('projects.card.sessionsWaiting', { waiting: card.sessions.waiting })
      }}</template>
    </p>

    <BudgetMeter :budget="card.budget" />

    <section class="flex flex-col gap-1.5">
      <h3 class="text-xs font-medium uppercase tracking-wider text-muted">
        {{ t('projects.card.openTasks') }}
      </h3>
      <TaskCounts :counts="card.open_tasks" />
    </section>

    <section class="flex flex-col gap-1" data-testid="latest-deliverable">
      <h3 class="text-xs font-medium uppercase tracking-wider text-muted">
        {{ t('projects.card.latest') }}
      </h3>
      <template v-if="card.latest_deliverable">
        <p class="break-words text-sm">{{ card.latest_deliverable.title }}</p>
        <Mono class="break-all text-xs text-muted">{{ card.latest_deliverable.branch }}</Mono>
      </template>
      <p v-else class="text-sm text-muted">{{ t('projects.card.noDeliverable') }}</p>
    </section>
  </li>
</template>
