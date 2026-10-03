<script setup lang="ts">
import { TriangleAlert } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import { formatMicros } from '@/format'
import { Mono } from '@/ui'

import type { Today } from './useToday'

defineProps<{ spend: Today['spend_without_output'] }>()
const { t } = useI18n()
</script>

<template>
  <section
    v-if="spend.length > 0"
    aria-labelledby="spend-title"
    class="flex flex-col gap-3"
    data-testid="spend-without-output"
  >
    <h2 id="spend-title" class="text-lg font-semibold">{{ t('today.spend.title') }}</h2>
    <ul class="glass divide-y divide-line rounded-xl border border-status-waiting/40">
      <li
        v-for="item in spend"
        :key="item.agent_id"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
        role="alert"
        data-testid="spend-warning"
      >
        <span class="flex items-center gap-2">
          <TriangleAlert class="size-4 text-status-waiting" aria-hidden="true" />
          {{
            t('today.spend.line', {
              agent: item.agent_title,
              project: item.project_name ?? t('today.spend.no_project'),
            })
          }}
        </span>
        <Mono class="font-medium">{{ formatMicros(item.cost_micros) }}</Mono>
      </li>
    </ul>
  </section>
</template>
