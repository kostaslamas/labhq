<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { components } from '@/api'
import { formatMicros } from '@/format'
import { Mono } from '@/ui'

type Deliverable = components['schemas']['Deliverable']

defineProps<{ items: Deliverable[]; total: number }>()
const { t, locale } = useI18n()

// An instant from the API is UTC; show it in the viewer's own zone and language.
function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(instant))
}

// The first seven characters name a commit well enough to read; the full name is the title.
const SHORT_COMMIT = 7
</script>

<template>
  <div class="flex flex-col gap-2">
    <p v-if="items.length === 0" class="text-sm text-muted">
      {{ t('projects.deliverables.empty') }}
    </p>
    <template v-else>
      <ul
        class="glass divide-y divide-line rounded-xl border border-line"
        data-testid="deliverables"
      >
        <li
          v-for="item in items"
          :key="item.task_id"
          class="grid gap-x-4 gap-y-1 p-4 sm:grid-cols-[minmax(0,1fr)_auto]"
          :data-task="item.task_id"
        >
          <div class="flex min-w-0 flex-col gap-1">
            <p class="break-words font-medium">{{ item.title }}</p>
            <Mono class="break-all text-xs text-muted" data-testid="deliverable-branch">
              {{ item.branch }}
            </Mono>
            <p v-if="item.commits.length" class="flex flex-wrap gap-x-2 text-xs">
              <Mono
                v-for="commit in item.commits"
                :key="commit"
                :title="commit"
                data-testid="deliverable-commit"
              >
                {{ commit.slice(0, SHORT_COMMIT) }}
              </Mono>
            </p>
            <p v-else class="text-xs text-muted">{{ t('projects.deliverables.unpublished') }}</p>
          </div>
          <div class="flex flex-col sm:items-end">
            <Mono data-testid="deliverable-cost">{{ formatMicros(item.cost_micros) }}</Mono>
            <span class="text-xs text-muted">{{ when(item.done_at) }}</span>
          </div>
        </li>
      </ul>
      <p v-if="total > items.length" class="text-xs text-muted">
        {{ t('projects.deliverables.more', { shown: items.length, total }) }}
      </p>
    </template>
  </div>
</template>
