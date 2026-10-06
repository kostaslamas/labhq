<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import ReportCard from '@/areas/ceo/ReportCard.vue'

import DeliveredList from './DeliveredList.vue'
import NeedsYou from './NeedsYou.vue'
import SpendWarnings from './SpendWarnings.vue'
import { useToday } from './useToday'

const { t } = useI18n()
const { today, failed, reload } = useToday()
</script>

<template>
  <section class="mx-auto flex max-w-5xl flex-col gap-8 p-4 sm:p-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('today.nav') }}</h1>
    <p v-if="failed" role="alert" class="text-status-failed">{{ t('today.failed') }}</p>
    <template v-if="today">
      <section v-if="today.ceo_report" class="flex flex-col gap-3" data-testid="today-ceo-report">
        <header class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="text-lg font-semibold">{{ t('ceo.latest') }}</h2>
          <RouterLink :to="{ name: 'ceo-chat' }" class="text-sm text-accent underline">
            {{ t('ceo.openChat') }}
          </RouterLink>
        </header>
        <ReportCard :report="today.ceo_report" @decided="reload" />
      </section>
      <NeedsYou :needs="today.needs_you" />
      <SpendWarnings :spend="today.spend_without_output" />
      <DeliveredList :deliverables="today.deliverables" />
    </template>
  </section>
</template>
