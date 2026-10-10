<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { api, type components } from '@/api'

import CeoAssignmentForm from '@/areas/projects/CeoAssignmentForm.vue'
import SessionScan from '@/areas/sessions/SessionScan.vue'
import type { FoundProject } from '@/areas/sessions/scan'

const { t } = useI18n()
const router = useRouter()
const kinds = ref<components['schemas']['AgentKindChoice'][]>([])
const failure = ref<string | null>(null)

onMounted(async () => {
  const { data } = await api.GET('/api/agent-kinds')
  kinds.value = data ?? []
})

// A found folder becomes a project with one manager of the chosen program. The manager waits
// for its approval, so nothing runs until the owner decides it on the Approvals page.
async function start(project: FoundProject, kind: string): Promise<void> {
  failure.value = null
  const created = await api.POST('/api/projects', {
    body: { name: project.name, repo_path: project.path },
  })
  if (!created.data) {
    failure.value = t('ceo.startFailed')
    return
  }
  const agent = await api.POST('/api/projects/{project_id}/agents', {
    params: { path: { project_id: created.data.id } },
    body: { role: 'manager', title: `${project.name} manager`, kind },
  })
  if (!agent.data) failure.value = t('ceo.startFailed')
  else await router.push({ name: 'project', params: { id: created.data.id } })
}

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

    <p v-if="failure" role="alert" class="text-status-failed" data-testid="ceo-start-failure">
      {{ failure }}
    </p>
    <SessionScan :kinds="kinds" @add="addFound" @start="start" />
  </section>
</template>
