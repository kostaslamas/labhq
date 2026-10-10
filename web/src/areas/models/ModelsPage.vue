<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useFailureMessage } from '@/areas/auth/useFailureMessage'
import { useStepUp } from '@/auth'
import { authClient } from '@/auth/client'
import { Button, Mono } from '@/ui'

import { savePolicy, type ModelCost, type Policy, type PolicyRow } from './models'

const i18n = useI18n()
const { t } = i18n
const stepUp = useStepUp()
const passkeyMessage = useFailureMessage()

const policy = ref<Policy | null>(null)
const rows = ref<PolicyRow[]>([])
const usage = ref<ModelCost[]>([])
const loadFailed = ref(false)
const failure = ref<string | null>(null)
const saved = ref(false)
const busy = ref(false)

function label(key: string): string {
  return i18n.te(`models.keys.${key}`) ? t(`models.keys.${key}`) : key
}

// Whole dollars would hide a Haiku run; four decimals show it.
function dollars(micros: number): string {
  return `$${(micros / 1_000_000).toFixed(4)}`
}

function per(model: string): string {
  const info = policy.value?.models.find((m) => m.id === model)
  if (info === undefined) return ''
  return t('models.price', {
    input: dollars(info.input_micros_per_mtok),
    output: dollars(info.output_micros_per_mtok),
  })
}

async function load(): Promise<void> {
  const [table, cost] = await Promise.all([
    authClient().GET('/api/models'),
    authClient().GET('/api/models/usage'),
  ])
  loadFailed.value = table.data === undefined
  if (table.data !== undefined) {
    policy.value = table.data
    rows.value = table.data.rows.map((r) => ({ ...r }))
  }
  if (cost.data !== undefined) usage.value = cost.data
}

async function save(): Promise<void> {
  if (busy.value) return
  busy.value = true
  failure.value = null
  saved.value = false
  try {
    const credential = await stepUp.requestAssertion('models:policy')
    if (credential === null) {
      failure.value = passkeyMessage(stepUp.failure.value ?? 'rejected')
      return
    }
    const result = await savePolicy(rows.value, credential)
    if (!result.ok) {
      failure.value = t(`models.errors.${result.failure}`)
      return
    }
    policy.value = result.value
    rows.value = result.value.rows.map((r) => ({ ...r }))
    saved.value = true
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-8">
    <header class="flex flex-col gap-2">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('models.title') }}</h1>
      <p class="text-muted">{{ t('models.lead') }}</p>
    </header>

    <p v-if="loadFailed" role="alert" class="text-status-failed">{{ t('models.load_failed') }}</p>
    <p v-else-if="policy === null" class="text-muted">{{ t('models.loading') }}</p>
    <p v-if="failure" role="alert" class="text-status-failed" data-testid="models-failure">
      {{ failure }}
    </p>
    <p v-if="saved" class="text-muted" data-testid="models-saved">{{ t('models.saved') }}</p>

    <form
      v-if="policy !== null"
      class="glass flex flex-col gap-4 rounded-xl border border-line p-4"
      data-testid="models-form"
      @submit.prevent="save"
    >
      <ul class="flex flex-col gap-3">
        <li
          v-for="row in rows"
          :key="row.key"
          :data-testid="`row-${row.key}`"
          class="flex flex-wrap items-center justify-between gap-3"
        >
          <div class="flex min-w-0 flex-col">
            <span class="font-medium">{{ label(row.key) }}</span>
            <span class="text-xs text-muted">{{
              row.kind === 'role' ? t('models.role') : t('models.task')
            }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <select
              v-model="row.model"
              :aria-label="`${label(row.key)} · ${t('models.model')}`"
              class="rounded-md border border-line bg-transparent p-2"
              :data-testid="`model-${row.key}`"
            >
              <option v-for="m in policy.models" :key="m.id" :value="m.id">
                {{ m.display_name }}
              </option>
            </select>
            <select
              v-model="row.effort"
              :aria-label="`${label(row.key)} · ${t('models.effort')}`"
              class="rounded-md border border-line bg-transparent p-2"
              :data-testid="`effort-${row.key}`"
            >
              <option v-for="e in policy.efforts" :key="e" :value="e">{{ e }}</option>
            </select>
          </div>
          <p class="w-full text-xs text-muted">{{ per(row.model) }}</p>
        </li>
      </ul>
      <p class="text-sm text-muted">{{ t('models.passkey_note') }}</p>
      <div>
        <Button type="submit" :disabled="busy" data-testid="save">{{ t('models.save') }}</Button>
      </div>
    </form>

    <section class="flex flex-col gap-2" data-testid="usage">
      <h2 class="text-lg font-medium">{{ t('models.usage') }}</h2>
      <p v-if="usage.length === 0" class="text-muted">{{ t('models.usage_empty') }}</p>
      <ul v-else class="flex flex-col gap-2">
        <li
          v-for="cost in usage"
          :key="cost.model"
          :data-testid="`usage-${cost.model}`"
          class="flex flex-wrap items-baseline justify-between gap-2"
        >
          <Mono>{{ cost.model }}</Mono>
          <span>
            {{ dollars(cost.cost_micros) }} · {{ t('models.usage_runs', { count: cost.runs }) }}
            <span v-if="cost.saved_micros !== null && cost.saved_micros > 0" class="text-muted">
              · {{ t('models.usage_saved', { amount: dollars(cost.saved_micros) }) }}
            </span>
          </span>
        </li>
      </ul>
    </section>
  </section>
</template>
