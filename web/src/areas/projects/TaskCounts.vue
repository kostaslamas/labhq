<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { components } from '@/api'
import { cn, Mono } from '@/ui'

import { taskStatusLabels } from './taskStatus'

type TaskCount = components['schemas']['TaskCount']

defineProps<{ counts: TaskCount[] }>()
const { t } = useI18n()
</script>

<template>
  <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm" data-testid="task-counts">
    <li
      v-for="entry in counts"
      :key="entry.status"
      :data-status="entry.status"
      :class="cn('flex items-center gap-1.5', entry.count === 0 && 'opacity-50')"
    >
      <span class="text-muted">{{ t(taskStatusLabels[entry.status].labelKey) }}</span>
      <Mono>{{ entry.count }}</Mono>
    </li>
  </ul>
</template>
