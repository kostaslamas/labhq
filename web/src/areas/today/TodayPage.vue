<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import ReportCard from '@/areas/ceo/ReportCard.vue'

import CapacityCard from './CapacityCard.vue'
import DeliveredList from './DeliveredList.vue'
import NeedsYou from './NeedsYou.vue'
import NewProjectsCard from './NewProjectsCard.vue'
import SpendWarnings from './SpendWarnings.vue'
import { useCapacity } from './useCapacity'
import { useNewProjects } from './useNewProjects'
import { useToday } from './useToday'

const { t } = useI18n()
const { today, failed, reload } = useToday()
const { capacity } = useCapacity()
const { projects: newProjects } = useNewProjects()
</script>

<template>
  <section class="mx-auto flex max-w-5xl flex-col gap-8 p-4 sm:p-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('today.nav') }}</h1>
    <p v-if="failed" role="alert" class="text-status-failed">{{ t('today.failed') }}</p>
    <CapacityCard v-if="capacity" :capacity="capacity" />
    <NewProjectsCard v-if="newProjects.length > 0" :projects="newProjects" />
    <template v-if="today">
      <section v-if="today.ceo_report" class="flex flex-col gap-3" data-testid="today-ceo-report">
        <h2 class="text-lg font-semibold">{{ t('ceo.latest') }}</h2>
        <ReportCard :report="today.ceo_report" @decided="reload" />
      </section>
      <NeedsYou :needs="today.needs_you" />
      <SpendWarnings :spend="today.spend_without_output" />
      <DeliveredList :deliverables="today.deliverables" />
    </template>
  </section>
</template>
