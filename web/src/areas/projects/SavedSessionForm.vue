<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'
import { Button } from '@/ui'

import { FIELD, LABEL } from './fieldClasses'

type Kind = components['schemas']['AgentKindChoice']
type Session = components['schemas']['SavedSessionChoice']
type Candidate = components['schemas']['RunningManagerCandidate']

const props = defineProps<{ projectId: number }>()
const emit = defineEmits<{ requested: [approvalId: number]; running: [kind: string]; cancel: [] }>()
const { t, locale } = useI18n()

const kinds = ref<Kind[]>([])
const kind = ref('')
const sessions = ref<Session[]>([])
const runningCandidates = ref<Candidate[]>([])
const sessionId = ref('')
const loading = ref(false)
const busy = ref(false)
const failure = ref('')

async function loadKinds(): Promise<void> {
  const { data } = await api.GET('/api/agent-kinds')
  if (!data) {
    failure.value = 'projects.sessions.loadFailed'
    return
  }
  kinds.value = data.filter((choice) => choice.adapter === 'tmux' && choice.available)
  kind.value =
    kinds.value.find((choice) => choice.name === 'claude-code')?.name ?? kinds.value[0]?.name ?? ''
}

async function loadSessions(): Promise<void> {
  sessions.value = []
  runningCandidates.value = []
  sessionId.value = ''
  if (!kind.value) return
  loading.value = true
  failure.value = ''
  const selected = kind.value
  try {
    const [saved, running] = await Promise.allSettled([
      api.GET('/api/projects/{project_id}/saved-sessions', {
        params: { path: { project_id: props.projectId }, query: { kind: selected } },
      }),
      api.GET('/api/projects/{project_id}/running-managers', {
        params: { path: { project_id: props.projectId } },
      }),
    ])
    if (selected !== kind.value) return
    if (saved.status === 'fulfilled' && saved.value.data) sessions.value = saved.value.data
    else failure.value = 'projects.sessions.loadFailed'
    if (running.status === 'fulfilled' && running.value.data) {
      runningCandidates.value = running.value.data.filter((agent) => agent.kind === selected)
    }
  } catch {
    failure.value = 'projects.sessions.loadFailed'
  } finally {
    if (selected === kind.value) loading.value = false
  }
}

async function handleRunning(): Promise<void> {
  const { data: active } = await api.GET('/api/projects/{project_id}/running-managers', {
    params: { path: { project_id: props.projectId } },
  })
  if (active?.some((agent) => agent.kind === kind.value)) emit('running', kind.value)
  else failure.value = 'projects.sessions.runningOutside'
}

async function submit(): Promise<void> {
  if (busy.value || !kind.value || !sessionId.value) return
  busy.value = true
  failure.value = ''
  try {
    const { data, error } = await api.POST('/api/projects/{project_id}/assign-saved-session', {
      params: { path: { project_id: props.projectId } },
      body: { kind: kind.value, session_id: sessionId.value },
    })
    if (data) emit('requested', data.approval_id)
    else {
      const code = (error as { error?: { code?: string } } | undefined)?.error?.code
      if (code === 'agent_running') await handleRunning()
      else failure.value = 'projects.sessions.assignFailed'
    }
  } catch {
    failure.value = 'projects.sessions.assignFailed'
  } finally {
    busy.value = false
  }
}

function updated(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(instant))
}

onMounted(loadKinds)
watch(kind, loadSessions)
</script>

<template>
  <form
    class="glass flex flex-col gap-4 rounded-xl border border-line p-5"
    data-testid="saved-session-form"
    @submit.prevent="submit"
  >
    <h3 class="text-base font-semibold">{{ t('projects.sessions.title') }}</h3>
    <p class="text-sm text-muted">{{ t('projects.sessions.hint') }}</p>
    <div
      v-if="runningCandidates.length"
      class="rounded-lg border border-line p-3 text-sm"
      role="status"
    >
      <p>{{ t('projects.sessions.runningAvailable') }}</p>
      <Button
        type="button"
        variant="outline"
        class="mt-2"
        data-testid="choose-running-agent"
        @click="emit('running', kind)"
      >
        {{ t('projects.sessions.chooseRunning') }}
      </Button>
    </div>
    <label :class="LABEL">
      {{ t('projects.sessions.kind') }}
      <select v-model="kind" :class="FIELD" required data-testid="saved-session-kind">
        <option v-for="choice in kinds" :key="choice.name" :value="choice.name">
          {{ choice.display_name }}
        </option>
      </select>
    </label>
    <p v-if="loading" class="text-sm text-muted">{{ t('projects.sessions.loading') }}</p>
    <label v-else-if="sessions.length" :class="LABEL">
      {{ t('projects.sessions.session') }}
      <select v-model="sessionId" :class="FIELD" required data-testid="saved-session-choice">
        <option value="" disabled>{{ t('projects.sessions.choose') }}</option>
        <option v-for="session in sessions" :key="session.session_id" :value="session.session_id">
          {{ updated(session.updated_at) }} · {{ session.session_id }}
        </option>
      </select>
    </label>
    <p v-else-if="kind && !failure" class="text-sm text-muted">
      {{ t('projects.sessions.empty') }}
    </p>
    <p v-if="failure" role="alert" class="text-sm text-status-failed">{{ t(failure) }}</p>
    <div class="flex flex-wrap gap-3">
      <Button type="submit" :disabled="busy || !sessionId" data-testid="saved-session-submit">
        {{ busy ? t('projects.sessions.working') : t('projects.sessions.submit') }}
      </Button>
      <Button type="button" variant="outline" :disabled="busy" @click="emit('cancel')">
        {{ t('projects.add.cancel') }}
      </Button>
    </div>
  </form>
</template>
