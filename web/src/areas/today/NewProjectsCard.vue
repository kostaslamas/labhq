<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { Mono } from '@/ui'

import type { NewProject } from './useNewProjects'

defineProps<{ projects: NewProject[] }>()
const { t } = useI18n()
</script>

<template>
  <section
    aria-labelledby="new-projects-title"
    class="glass flex flex-col gap-3 rounded-xl border border-line p-4"
    data-testid="new-projects"
  >
    <h2 id="new-projects-title" class="text-lg font-semibold">
      {{ t('today.newProjects.title', projects.length) }}
    </h2>
    <ul class="flex flex-col gap-1">
      <li v-for="project in projects" :key="project.path" class="flex flex-col">
        <span class="font-medium">{{ project.name }}</span>
        <Mono class="break-all text-xs text-muted">{{ project.path }}</Mono>
      </li>
    </ul>
    <RouterLink
      :to="{ name: 'projects', query: { panel: 'scan' } }"
      class="w-fit text-accent underline"
      data-testid="new-projects-link"
    >
      {{ t('today.newProjects.review') }}
    </RouterLink>
  </section>
</template>
