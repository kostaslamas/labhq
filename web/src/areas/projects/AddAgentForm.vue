<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'
import { Button } from '@/ui'

import { errorKey } from './authoringErrors'
import { FIELD, LABEL } from './fieldClasses'
import { usdToMicros } from './usd'

type Kind = components['schemas']['AgentKindChoice']
type Member = components['schemas']['TeamMember']

const props = defineProps<{ projectId: number; team: Member[] }>()
const emit = defineEmits<{ added: [approvalId: number]; cancel: [] }>()
const { t } = useI18n()

// The reporting lines of plan §2; the server refuses any other pairing.
const ROLES = ['manager', 'lead', 'worker', 'it'] as const

const kinds = ref<Kind[]>([])
const kindsState = ref<'loading' | 'ready' | 'failed'>('loading')
const role = ref<string>('worker')
const title = ref('')
const kind = ref('')
const reportsTo = ref('')
const budget = ref('')
const busy = ref(false)
const failure = ref<string | null>(null)

function flatten(members: Member[]): Member[] {
  return members.flatMap((member) => [member, ...flatten(member.reports)])
}
const people = computed(() => flatten(props.team))

async function loadKinds(): Promise<void> {
  const { data } = await api.GET('/api/agent-kinds')
  if (!data) {
    kindsState.value = 'failed'
    return
  }
  kinds.value = data
  // The first kind that can run here, so a fresh form is one title away from valid.
  kind.value = data.find((candidate) => candidate.available)?.name ?? ''
  kindsState.value = 'ready'
}

function kindLabel(candidate: Kind): string {
  return candidate.available
    ? candidate.display_name
    : `${candidate.display_name}: ${t('projects.agent.missing', { binary: candidate.binary })}`
}

async function submit(): Promise<void> {
  if (busy.value) return
  const micros = usdToMicros(budget.value)
  if (micros === undefined) {
    failure.value = 'projects.errors.budget'
    return
  }
  busy.value = true
  failure.value = null
  try {
    const { data, error } = await api.POST('/api/projects/{project_id}/agents', {
      params: { path: { project_id: props.projectId } },
      body: {
        role: role.value,
        title: title.value.trim(),
        kind: kind.value,
        reports_to:
          role.value === 'manager' || reportsTo.value === '' ? null : Number(reportsTo.value),
        budget_micros: micros,
      },
    })
    if (data) emit('added', data.approval_id)
    else failure.value = errorKey(error)
  } catch {
    failure.value = 'projects.errors.network'
  } finally {
    busy.value = false
  }
}

onMounted(loadKinds)
</script>

<template>
  <form
    class="glass flex flex-col gap-4 rounded-xl border border-line p-5"
    data-testid="add-agent-form"
    @submit.prevent="submit"
  >
    <h3 class="text-base font-semibold">{{ t('projects.agent.title') }}</h3>
    <label :class="LABEL">
      {{ t('projects.agent.name') }}
      <input v-model="title" :class="FIELD" required maxlength="200" name="title" />
    </label>
    <label :class="LABEL">
      {{ t('projects.agent.kind') }}
      <select v-model="kind" :class="FIELD" required name="kind" data-testid="agent-kind">
        <option
          v-for="candidate in kinds"
          :key="candidate.name"
          :value="candidate.name"
          :disabled="!candidate.available"
        >
          {{ kindLabel(candidate) }}
        </option>
      </select>
      <span v-if="kindsState === 'failed'" role="alert" class="text-xs text-status-failed">
        {{ t('projects.agent.kindsFailed') }}
      </span>
    </label>
    <label :class="LABEL">
      {{ t('projects.agent.role') }}
      <select v-model="role" :class="FIELD" required name="role">
        <option v-for="key in ROLES" :key="key" :value="key">
          {{ t(`projects.agent.roles.${key}`) }}
        </option>
      </select>
    </label>
    <label :class="LABEL">
      {{ t('projects.agent.reportsTo') }}
      <span v-if="role === 'manager'" class="text-sm text-muted">{{
        t('projects.agent.globalCeo')
      }}</span>
      <select v-else v-model="reportsTo" :class="FIELD" name="reports_to">
        <option value="">{{ t('projects.agent.nobody') }}</option>
        <option v-for="person in people" :key="person.id" :value="String(person.id)">
          {{ person.title }} ({{ person.role }})
        </option>
      </select>
    </label>
    <label :class="LABEL">
      {{ t('projects.add.budget') }}
      <input
        v-model="budget"
        :class="[FIELD, 'font-mono']"
        inputmode="decimal"
        name="budget"
        autocomplete="off"
      />
    </label>
    <p class="text-xs text-muted">{{ t('projects.agent.pendingHint') }}</p>
    <p v-if="failure" role="alert" class="text-sm text-status-failed" data-testid="form-error">
      {{ t(failure) }}
    </p>
    <div class="flex flex-wrap gap-3">
      <Button type="submit" :disabled="busy || kind === ''" data-testid="add-agent-submit">
        {{ busy ? t('projects.add.working') : t('projects.agent.submit') }}
      </Button>
      <Button type="button" variant="outline" :disabled="busy" @click="emit('cancel')">
        {{ t('projects.add.cancel') }}
      </Button>
    </div>
  </form>
</template>
