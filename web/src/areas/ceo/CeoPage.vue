<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import CeoAssignmentForm from '@/areas/projects/CeoAssignmentForm.vue'
import SessionScan from '@/areas/sessions/SessionScan.vue'
import type { FoundProject } from '@/areas/sessions/scan'

const { t } = useI18n()
const router = useRouter()

// A found folder becomes a project in the Projects tab, with its name and folder filled in.
function addFound(project: FoundProject): void {
  void router.push({ name: 'projects', query: { add: project.path, name: project.name } })
}
</script>

<template>
  <section class="mx-auto flex max-w-7xl flex-col gap-6 p-4 sm:p-8">
    <div class="flex flex-col gap-1">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('ceo.nav') }}</h1>
      <p class="text-sm text-muted">{{ t('ceo.lead') }}</p>
    </div>

    <CeoAssignmentForm />

    <SessionScan @add="addFound" />
  </section>
</template>
