<script setup lang="ts">
import { TriangleAlert } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import { Mono } from '@/ui'

import type { RunCapacity } from './useCapacity'

defineProps<{ capacity: RunCapacity }>()
const { t } = useI18n()
</script>

<template>
  <section
    aria-labelledby="capacity-title"
    class="glass flex flex-col gap-3 rounded-xl border p-4"
    :class="capacity.paused_for_memory ? 'border-status-waiting/40' : 'border-line'"
    data-testid="capacity"
    :data-paused="capacity.paused_for_memory"
  >
    <h2 id="capacity-title" class="text-lg font-semibold">{{ t('today.capacity.title') }}</h2>
    <p
      v-if="capacity.paused_for_memory"
      role="alert"
      class="flex items-center gap-2 text-status-waiting"
      data-testid="capacity-paused"
    >
      <TriangleAlert class="size-4" aria-hidden="true" />
      {{
        t('today.capacity.paused', {
          free: capacity.free_memory_percent,
          floor: capacity.min_free_memory_percent,
        })
      }}
    </p>
    <dl class="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <div>
        <dt class="text-sm text-muted">{{ t('today.capacity.running') }}</dt>
        <dd data-testid="capacity-running">
          <Mono class="font-medium">{{ capacity.running }} / {{ capacity.max_running }}</Mono>
        </dd>
      </div>
      <div>
        <dt class="text-sm text-muted">{{ t('today.capacity.memory') }}</dt>
        <dd data-testid="capacity-memory">
          <Mono class="font-medium">{{ capacity.free_memory_percent }}%</Mono>
        </dd>
      </div>
      <div>
        <dt class="text-sm text-muted">{{ t('today.capacity.floor') }}</dt>
        <dd>
          <Mono class="font-medium">{{ capacity.min_free_memory_percent }}%</Mono>
        </dd>
      </div>
      <div>
        <dt class="text-sm text-muted">{{ t('today.capacity.waiting') }}</dt>
        <dd data-testid="capacity-waiting">
          <Mono class="font-medium">{{ capacity.waiting }}</Mono>
        </dd>
      </div>
    </dl>
  </section>
</template>
