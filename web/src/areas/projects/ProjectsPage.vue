<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { api, type components } from '@/api'
import { useLiveTopic } from '@/live'
import { Button } from '@/ui'

import AddProjectForm from './AddProjectForm.vue'
import ProjectCard from './ProjectCard.vue'

type Card = components['schemas']['ProjectCard']

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const cards = ref<Card[]>([])
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const adding = ref(false)

// Follows the cursors to the end: a person's projects are a handful, and a grid with a
// hidden tail would hide a project that is over its budget.
async function load(): Promise<void> {
  const all: Card[] = []
  let cursor: string | undefined
  do {
    const { data } = await api.GET('/api/projects', { params: { query: { cursor } } })
    if (!data) {
      state.value = 'failed'
      return
    }
    all.push(...data.items)
    cursor = data.next_cursor ?? undefined
  } while (cursor)
  cards.value = all
  state.value = 'ready'
}

// `/projects?task=<id>` (a link from a meeting's action item) opens the project owning the task.
async function openTaskProject(): Promise<void> {
  const task = Number(route.query.task)
  if (!Number.isSafeInteger(task) || task <= 0) return
  const { data } = await api.GET('/api/projects/of-task/{task_id}', {
    params: { path: { task_id: task } },
  })
  if (data) await router.replace({ name: 'project', params: { id: data.project_id } })
}

// The new project's own page is where its first agent is added.
async function opened(id: number): Promise<void> {
  adding.value = false
  await router.push({ name: 'project', params: { id } })
}

onMounted(() => {
  void load()
  void openTaskProject()
})
for (const topic of ['tasks', 'runs', 'costs']) useLiveTopic(topic, load)
</script>

<template>
  <section class="mx-auto flex max-w-7xl flex-col gap-6 p-4 sm:p-8">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('projects.nav') }}</h1>
      <Button v-if="!adding" data-testid="add-project" @click="adding = true">
        {{ t('projects.add.button') }}
      </Button>
    </div>

    <AddProjectForm v-if="adding" class="max-w-xl" @added="opened" @cancel="adding = false" />

    <div v-if="state === 'failed'" role="alert" class="flex flex-wrap items-center gap-3">
      <p class="text-status-failed">{{ t('projects.loadFailed') }}</p>
      <Button variant="outline" size="sm" @click="load">{{ t('projects.retry') }}</Button>
    </div>
    <p v-else-if="state === 'loading'" class="text-muted">{{ t('projects.loading') }}</p>
    <p v-else-if="cards.length === 0" class="glass rounded-xl border border-line p-6 text-muted">
      {{ t('projects.empty') }}
    </p>
    <ul
      v-else
      class="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,20rem),1fr))]"
      data-testid="project-grid"
    >
      <ProjectCard v-for="card in cards" :key="card.id" :card="card" />
    </ul>
  </section>
</template>
