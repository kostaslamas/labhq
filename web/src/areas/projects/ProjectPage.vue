<script setup lang="ts">
import { ArrowLeft } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, uiState, type components } from '@/api'
import { useLiveTopic } from '@/live'
import { StatusBadge } from '@/status'
import ProjectSessions from '@/areas/sessions/ProjectSessions.vue'
import { loadSessions, type ScannedProject } from '@/areas/sessions/sessions'
import { Button, Mono } from '@/ui'

import AddAgentForm from './AddAgentForm.vue'
import EditAgentForm from './EditAgentForm.vue'
import AdoptManagerForm from './AdoptManagerForm.vue'
import SavedSessionForm from './SavedSessionForm.vue'
import BudgetMeter from './BudgetMeter.vue'
import DeliverableList from './DeliverableList.vue'
import TaskCounts from './TaskCounts.vue'
import TeamTree from './TeamTree.vue'

type View = components['schemas']['ProjectView']

const props = defineProps<{ id: string }>()
const { t, locale } = useI18n()
const view = ref<View | null>(null)
const state = ref<'loading' | 'ready' | 'missing' | 'failed'>('loading')
const adding = ref(false)
// This project's sessions from the last scan, with the proposed actions; none before a scan.
const scanned = ref<ScannedProject | null>(null)
const editing = ref<number | null>(null)
const awaiting = ref(false)
const adopting = ref(false)
const adoptingKind = ref<string | null>(null)
const assigningSaved = ref(false)
const adoptionRequested = ref(false)
const hasManager = computed(
  () =>
    view.value?.team.some((member) => member.role === 'manager' && member.status !== 'retired') ??
    false,
)
function findMember(
  members: components['schemas']['TeamMember'][],
  id: number,
): components['schemas']['TeamMember'] | null {
  for (const member of members) {
    if (member.id === id) return member
    const nested = findMember(member.reports, id)
    if (nested) return nested
  }
  return null
}
const editedMember = computed(() =>
  view.value && editing.value !== null ? findMember(view.value.team, editing.value) : null,
)

async function agentSaved(): Promise<void> {
  editing.value = null
  await load()
}

function managerRequested(): void {
  adoptionRequested.value = true
  adopting.value = false
  assigningSaved.value = false
}

function useRunningAgent(kind: string): void {
  assigningSaved.value = false
  adoptingKind.value = kind
  adopting.value = true
}

function chooseRunningAgent(): void {
  adoptingKind.value = null
  adopting.value = true
}

async function agentAdded(): Promise<void> {
  adding.value = false
  awaiting.value = true
  await load()
}

async function load(): Promise<void> {
  const projectId = Number(props.id)
  if (!Number.isSafeInteger(projectId)) {
    state.value = 'missing'
    return
  }
  const { data, response } = await api.GET('/api/projects/{project_id}', {
    params: { path: { project_id: projectId } },
  })
  if (data) {
    view.value = data
    state.value = 'ready'
  } else {
    state.value = response.status === 404 ? 'missing' : 'failed'
  }
}

function since(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(instant))
}

async function loadScanned(): Promise<void> {
  const sessions = await loadSessions()
  scanned.value = sessions?.projects.find((p) => p.project_id === Number(props.id)) ?? null
}

onMounted(() => {
  void load()
  void loadScanned()
})
watch(() => props.id, load)
for (const topic of ['tasks', 'runs', 'costs']) useLiveTopic(topic, load)
</script>

<template>
  <section class="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-8">
    <RouterLink
      :to="{ name: 'projects' }"
      class="inline-flex w-fit items-center gap-1.5 text-sm text-muted hover:text-foreground"
    >
      <ArrowLeft class="size-4" aria-hidden="true" />
      {{ t('projects.back') }}
    </RouterLink>

    <p v-if="state === 'missing'" role="alert" class="text-status-failed">
      {{ t('projects.notFound') }}
    </p>
    <div v-else-if="state === 'failed'" role="alert" class="flex flex-wrap items-center gap-3">
      <p class="text-status-failed">{{ t('projects.loadFailed') }}</p>
      <Button variant="outline" size="sm" @click="load">{{ t('projects.retry') }}</Button>
    </div>
    <p v-else-if="state === 'loading' || !view" class="text-muted">{{ t('projects.loading') }}</p>

    <template v-else>
      <header class="flex flex-wrap items-center gap-3">
        <h1 class="min-w-0 break-words text-2xl font-semibold tracking-wide">{{ view.name }}</h1>
        <StatusBadge :state="uiState('project_status', view.status)" />
        <RouterLink
          v-if="view.name === 'infra'"
          :to="{ name: 'rules' }"
          class="text-sm text-muted underline hover:text-foreground"
          data-testid="rules-link"
        >
          {{ t('projects.rulesLink') }}
        </RouterLink>
      </header>

      <section class="glass flex flex-col gap-3 rounded-xl border border-line p-5">
        <h2 class="text-lg font-semibold">{{ t('projects.view.budget') }}</h2>
        <BudgetMeter :budget="view.budget" />
        <p class="text-xs text-muted">
          {{
            t('projects.view.policy', {
              warn: view.policy.warn_percent,
              stop: view.policy.stop_percent,
              since: since(view.policy.period_start),
            })
          }}
        </p>
      </section>

      <section v-if="scanned" class="flex flex-col gap-3" data-testid="project-sessions">
        <h2 class="text-lg font-semibold">{{ t('projects.sessionsTitle') }}</h2>
        <ul>
          <ProjectSessions :project="scanned" />
        </ul>
      </section>

      <section class="flex flex-col gap-3">
        <h2 class="text-lg font-semibold">{{ t('projects.view.tasks') }}</h2>
        <TaskCounts :counts="view.tasks" />
      </section>

      <section class="flex flex-col gap-3">
        <h2 class="text-lg font-semibold">{{ t('projects.view.deliverables') }}</h2>
        <DeliverableList :items="view.deliverables" :total="view.deliverables_total" />
      </section>

      <section class="glass flex flex-col gap-3 rounded-xl border border-line p-5">
        <h2 class="text-lg font-semibold">
          {{ t('projects.view.team') }}
          <Mono class="text-sm text-muted">#{{ view.id }}</Mono>
        </h2>
        <TeamTree :team="view.team" @edit="editing = $event" />
        <EditAgentForm
          v-if="editedMember"
          :key="editedMember.id"
          :project-id="view.id"
          :member="editedMember"
          :team="view.team"
          @saved="agentSaved"
          @cancel="editing = null"
        />
        <p v-if="adoptionRequested" role="status" class="text-sm text-muted">
          {{ t('projects.adopt.waiting') }}
          <RouterLink :to="{ name: 'approvals' }" class="text-accent underline">
            {{ t('projects.agent.review') }}
          </RouterLink>
        </p>
        <AdoptManagerForm
          v-if="adopting"
          :project-id="view.id"
          :kind="adoptingKind"
          @requested="managerRequested"
          @cancel="adopting = false"
        />
        <SavedSessionForm
          v-if="assigningSaved"
          :project-id="view.id"
          @requested="managerRequested"
          @running="useRunningAgent"
          @cancel="assigningSaved = false"
        />
        <div
          v-if="!hasManager && !adoptionRequested && !adopting && !assigningSaved"
          class="flex flex-wrap gap-3"
        >
          <Button
            variant="outline"
            data-testid="assign-saved-session"
            @click="assigningSaved = true"
          >
            {{ t('projects.sessions.button') }}
          </Button>
          <Button variant="outline" data-testid="adopt-manager" @click="chooseRunningAgent">
            {{ t('projects.adopt.button') }}
          </Button>
        </div>
        <p
          v-if="awaiting"
          role="status"
          class="flex flex-wrap items-center gap-2 text-sm text-muted"
          data-testid="agent-waiting"
        >
          {{ t('projects.agent.waiting') }}
          <RouterLink :to="{ name: 'approvals' }" class="text-accent underline">
            {{ t('projects.agent.review') }}
          </RouterLink>
        </p>
        <AddAgentForm
          v-if="adding"
          :project-id="view.id"
          :team="view.team"
          @added="agentAdded"
          @cancel="adding = false"
        />
        <Button
          v-else
          class="w-fit"
          variant="outline"
          data-testid="add-agent"
          @click="adding = true"
        >
          {{ t('projects.agent.button') }}
        </Button>
      </section>
    </template>
  </section>
</template>
