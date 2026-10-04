<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'
import { Button } from '@/ui'

import { FIELD, LABEL } from './fieldClasses'

type Kind = components['schemas']['AgentKindChoice']

const { t } = useI18n()
const kinds = ref<Kind[]>([])
const primary = ref('')
const backup = ref('')
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const saving = ref(false)
const saved = ref(false)
const failure = ref(false)

async function load(): Promise<void> {
  const [choices, assignment] = await Promise.all([
    api.GET('/api/agent-kinds'),
    api.GET('/api/org/ceo'),
  ])
  if (!choices.data || !assignment.data) {
    state.value = 'failed'
    return
  }
  kinds.value = choices.data
  primary.value =
    assignment.data.primary_kind ?? choices.data.find((kind) => kind.available)?.name ?? ''
  backup.value = assignment.data.backup_kind ?? ''
  state.value = 'ready'
}

async function save(): Promise<void> {
  if (saving.value || !primary.value || primary.value === backup.value) return
  saving.value = true
  saved.value = false
  failure.value = false
  try {
    const { data } = await api.PUT('/api/org/ceo', {
      body: { primary_kind: primary.value, backup_kind: backup.value || null },
    })
    if (data) {
      primary.value = data.primary_kind ?? ''
      backup.value = data.backup_kind ?? ''
      saved.value = true
    } else failure.value = true
  } catch {
    failure.value = true
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section
    class="glass flex max-w-xl flex-col gap-4 rounded-xl border border-line p-5"
    data-testid="ceo-assignment"
  >
    <div>
      <h2 class="text-lg font-semibold">{{ t('projects.ceo.title') }}</h2>
      <p class="text-sm text-muted">{{ t('projects.ceo.hint') }}</p>
    </div>
    <p v-if="state === 'loading'" class="text-sm text-muted">{{ t('projects.loading') }}</p>
    <p v-else-if="state === 'failed'" role="alert" class="text-sm text-status-failed">
      {{ t('projects.ceo.loadFailed') }}
    </p>
    <form v-else class="flex flex-col gap-4" @submit.prevent="save">
      <label :class="LABEL">
        {{ t('projects.ceo.primary') }}
        <select v-model="primary" :class="FIELD" required data-testid="ceo-primary">
          <option
            v-for="kind in kinds"
            :key="kind.name"
            :value="kind.name"
            :disabled="!kind.available"
          >
            {{ kind.display_name }}{{ kind.available ? '' : ` (${t('projects.ceo.unavailable')})` }}
          </option>
        </select>
      </label>
      <label :class="LABEL">
        {{ t('projects.ceo.backup') }}
        <select v-model="backup" :class="FIELD" data-testid="ceo-backup">
          <option value="">{{ t('projects.ceo.noBackup') }}</option>
          <option
            v-for="kind in kinds"
            :key="kind.name"
            :value="kind.name"
            :disabled="!kind.available || kind.name === primary"
          >
            {{ kind.display_name }}{{ kind.available ? '' : ` (${t('projects.ceo.unavailable')})` }}
          </option>
        </select>
      </label>
      <p v-if="failure" role="alert" class="text-sm text-status-failed">
        {{ t('projects.ceo.failed') }}
      </p>
      <p v-if="saved" role="status" class="text-sm text-muted" data-testid="ceo-saved">
        {{ t('projects.ceo.saved') }}
      </p>
      <Button
        type="submit"
        class="self-start"
        :disabled="saving || !primary || primary === backup"
        data-testid="ceo-save"
      >
        {{ saving ? t('projects.ceo.saving') : t('projects.ceo.save') }}
      </Button>
    </form>
  </section>
</template>
