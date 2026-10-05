<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api } from '@/api'
import { Button } from '@/ui'

import { FIELD, LABEL } from './fieldClasses'

const props = defineProps<{ projectId: number; kind?: string | null }>()
const emit = defineEmits<{ requested: [approvalId: number]; cancel: [] }>()
const { t } = useI18n()

type Candidate = {
  pid: number
  kind: string
  cwd: string
  pane: string
}

const candidates = ref<Candidate[]>([])
const selectedPid = ref('')
const loading = ref(true)
const busy = ref(false)
const failure = ref(false)

async function load(): Promise<void> {
  loading.value = true
  failure.value = false
  try {
    const { data } = await api.GET('/api/projects/{project_id}/running-managers', {
      params: { path: { project_id: props.projectId } },
    })
    if (!data) failure.value = true
    else {
      candidates.value = props.kind ? data.filter((agent) => agent.kind === props.kind) : data
      selectedPid.value = candidates.value.length === 1 ? String(candidates.value[0]!.pid) : ''
    }
  } catch {
    failure.value = true
  } finally {
    loading.value = false
  }
}

async function submit(): Promise<void> {
  if (busy.value || !selectedPid.value) return
  busy.value = true
  failure.value = false
  try {
    const { data } = await api.POST('/api/projects/{project_id}/adopt-manager', {
      params: { path: { project_id: props.projectId } },
      body: { pid: Number(selectedPid.value) },
    })
    if (data) emit('requested', data.approval_id)
    else failure.value = true
  } catch {
    failure.value = true
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <form
    class="glass flex flex-col gap-4 rounded-xl border border-line p-5"
    @submit.prevent="submit"
  >
    <h3 class="text-base font-semibold">{{ t('projects.adopt.title') }}</h3>
    <p class="text-sm text-muted">{{ t('projects.adopt.hint') }}</p>
    <p v-if="kind" class="text-sm text-muted" role="status">{{ t('projects.adopt.fromSaved') }}</p>
    <p v-if="loading" class="text-sm text-muted">{{ t('projects.adopt.loading') }}</p>
    <p v-else-if="candidates.length === 0" class="text-sm text-muted">
      {{ t(kind ? 'projects.adopt.outsideTmux' : 'projects.adopt.empty') }}
    </p>
    <label v-else :class="LABEL">
      {{ t('projects.adopt.agent') }}
      <select v-model="selectedPid" :class="FIELD" required data-testid="running-manager">
        <option value="" disabled>{{ t('projects.adopt.choose') }}</option>
        <option v-for="candidate in candidates" :key="candidate.pid" :value="String(candidate.pid)">
          {{ candidate.kind }} · {{ candidate.pane }} · PID {{ candidate.pid }} ·
          {{ candidate.cwd }}
        </option>
      </select>
    </label>
    <p v-if="failure" role="alert" class="text-sm text-status-failed">
      {{ t('projects.adopt.failed') }}
    </p>
    <div class="flex flex-wrap gap-3">
      <Button type="submit" :disabled="busy || !selectedPid" data-testid="adopt-manager-submit">
        {{ busy ? t('projects.adopt.working') : t('projects.adopt.submit') }}
      </Button>
      <Button type="button" variant="outline" :disabled="busy" @click="emit('cancel')">
        {{ t('projects.add.cancel') }}
      </Button>
    </div>
  </form>
</template>
