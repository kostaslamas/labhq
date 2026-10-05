<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'
import { Button } from '@/ui'

import { errorKey } from './authoringErrors'
import { FIELD, LABEL } from './fieldClasses'
import { usdToMicros } from './usd'

type Member = components['schemas']['TeamMember']
type Kind = components['schemas']['AgentKindChoice']

const props = defineProps<{ projectId: number; member: Member; team: Member[] }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()
const { t } = useI18n()
const title = ref(props.member.title)
const kind = ref(props.member.kind)
const reportsTo = ref(props.member.reports_to === null ? '' : String(props.member.reports_to))
const budget = ref(
  props.member.budget.budget_micros === null
    ? ''
    : `${Math.trunc(props.member.budget.budget_micros / 1_000_000)}.${String(props.member.budget.budget_micros % 1_000_000).padStart(6, '0')}`,
)
const kinds = ref<Kind[]>([])
const busy = ref(false)
const failure = ref<string | null>(null)

function flatten(members: Member[]): Member[] {
  return members.flatMap((member) => [member, ...flatten(member.reports)])
}
const excluded = computed(() => new Set(flatten([props.member]).map((member) => member.id)))
const parents = computed(() =>
  flatten(props.team).filter(
    (member) => !excluded.value.has(member.id) && member.status !== 'retired',
  ),
)

onMounted(async () => {
  try {
    const { data } = await api.GET('/api/agent-kinds')
    if (data) kinds.value = data
  } catch {
    failure.value = 'projects.agent.kindsFailed'
  }
})

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
    const { data, error } = await api.PATCH('/api/projects/{project_id}/agents/{agent_id}', {
      params: { path: { project_id: props.projectId, agent_id: props.member.id } },
      body: {
        title: title.value.trim(),
        kind: kind.value,
        reports_to:
          props.member.role === 'manager'
            ? props.member.reports_to
            : reportsTo.value
              ? Number(reportsTo.value)
              : null,
        budget_micros: micros,
      },
    })
    if (data) emit('saved')
    else failure.value = errorKey(error)
  } catch {
    failure.value = 'projects.errors.network'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form
    class="glass flex flex-col gap-4 rounded-xl border border-line p-5"
    data-testid="edit-agent-form"
    @submit.prevent="submit"
  >
    <h3 class="text-base font-semibold">{{ t('projects.agent.editTitle') }}</h3>
    <label :class="LABEL">
      {{ t('projects.agent.name') }}
      <input v-model="title" :class="FIELD" required maxlength="200" name="title" />
    </label>
    <label :class="LABEL">
      {{ t('projects.agent.kind') }}
      <select v-model="kind" :class="FIELD" :disabled="member.adopted" name="kind">
        <option
          v-if="!kinds.some((candidate) => candidate.name === member.kind)"
          :value="member.kind"
        >
          {{ member.kind }}
        </option>
        <option
          v-for="candidate in kinds"
          :key="candidate.name"
          :value="candidate.name"
          :disabled="!candidate.available && candidate.name !== member.kind"
        >
          {{ candidate.display_name }}
        </option>
      </select>
      <span v-if="member.adopted" class="text-xs font-normal text-muted">{{
        t('projects.agent.adoptedHint')
      }}</span>
    </label>
    <label v-if="member.role !== 'manager'" :class="LABEL">
      {{ t('projects.agent.reportsTo') }}
      <select v-model="reportsTo" :class="FIELD" name="reports_to">
        <option value="">{{ t('projects.agent.nobody') }}</option>
        <option v-for="person in parents" :key="person.id" :value="String(person.id)">
          {{ person.title }} ({{ person.role }})
        </option>
      </select>
    </label>
    <label :class="LABEL">
      {{ t('projects.add.budget') }}
      <input v-model="budget" :class="[FIELD, 'font-mono']" inputmode="decimal" name="budget" />
    </label>
    <p v-if="failure" role="alert" class="text-sm text-status-failed">{{ t(failure) }}</p>
    <div class="flex flex-wrap gap-3">
      <Button type="submit" :disabled="busy">{{
        busy ? t('projects.add.working') : t('projects.agent.save')
      }}</Button>
      <Button type="button" variant="outline" :disabled="busy" @click="emit('cancel')">{{
        t('projects.add.cancel')
      }}</Button>
    </div>
  </form>
</template>
