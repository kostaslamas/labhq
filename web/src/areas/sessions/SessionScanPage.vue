<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useFailureMessage } from '@/areas/auth/useFailureMessage'
import { useStepUp } from '@/auth'
import { authClient } from '@/auth/client'
import { Button, Mono } from '@/ui'

import { addRoot, removeRoot, type Change, type ScanRoot, type Scope } from './scope'

const PURPOSE = 'session_scan:roots'

const { t } = useI18n()
const stepUp = useStepUp()
const passkeyMessage = useFailureMessage()

const scope = ref<Scope | null>(null)
const loadFailed = ref(false)
const failure = ref<string | null>(null)
const warning = ref<string | null>(null)
const busy = ref(false)
const path = ref('')

async function load(): Promise<void> {
  const { data } = await authClient().GET('/api/session-scan')
  loadFailed.value = data === undefined
  if (data !== undefined) {
    scope.value = data
    if (path.value === '' && data.roots.length === 0) path.value = data.suggestion ?? ''
  }
}

/** One change that needs the passkey: it is asked for now, when the button is pressed. */
async function guarded(
  run: (
    credential: NonNullable<Awaited<ReturnType<typeof stepUp.requestAssertion>>>,
  ) => Promise<Change>,
): Promise<boolean> {
  if (busy.value) return false
  busy.value = true
  failure.value = null
  warning.value = null
  try {
    const credential = await stepUp.requestAssertion(PURPOSE)
    if (credential === null) {
      failure.value = passkeyMessage(stepUp.failure.value ?? 'rejected')
      return false
    }
    const result = await run(credential)
    if (!result.ok) {
      failure.value = result.detail ?? t(`sessions.errors.${result.failure}`)
      return false
    }
    scope.value = result.scope
    warning.value = result.warning
    return true
  } finally {
    busy.value = false
  }
}

async function add(): Promise<void> {
  const wanted = path.value.trim()
  if (wanted === '') return
  if (await guarded((credential) => addRoot(wanted, credential))) path.value = ''
}

function remove(root: ScanRoot): Promise<boolean> {
  return guarded((credential) => removeRoot(root.path, credential))
}

onMounted(load)
</script>

<template>
  <section class="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-8">
    <header class="flex flex-col gap-2">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('sessions.title') }}</h1>
      <p class="text-muted">{{ t('sessions.lead') }}</p>
    </header>

    <p v-if="loadFailed" role="alert" class="text-status-failed">{{ t('sessions.load_failed') }}</p>
    <p v-else-if="scope === null" class="text-muted">{{ t('sessions.loading') }}</p>
    <p v-if="failure" role="alert" class="text-status-failed" data-testid="sessions-failure">
      {{ failure }}
    </p>
    <p v-if="warning" class="text-status-waiting" data-testid="sessions-warning">{{ warning }}</p>

    <section
      v-if="scope !== null"
      class="glass flex flex-col gap-4 rounded-xl border border-line p-4"
    >
      <p v-if="scope.machine_wide" class="text-muted" data-testid="machine-wide">
        {{ t('sessions.machine_wide') }}
      </p>
      <ul v-else class="flex flex-col gap-3" data-testid="roots">
        <li
          v-for="root in scope.roots"
          :key="root.path"
          :data-testid="`root-${root.path}`"
          class="flex flex-wrap items-center justify-between gap-3"
        >
          <Mono class="min-w-0 break-all">{{ root.path }}</Mono>
          <Button v-if="root.removable" :disabled="busy" @click="remove(root)">
            {{ t('sessions.remove') }}
          </Button>
          <span v-else class="text-xs text-muted">{{ t('sessions.from_environment') }}</span>
        </li>
      </ul>

      <p v-if="scope.exclude.length > 0" class="text-sm text-muted" data-testid="excluded">
        {{ t('sessions.excluded', { folders: scope.exclude.join(', ') }) }}
      </p>

      <form class="flex flex-col gap-2" data-testid="add-root" @submit.prevent="add">
        <label class="flex flex-col gap-1">
          <span class="font-medium">{{ t('sessions.add') }}</span>
          <input
            v-model="path"
            type="text"
            autocomplete="off"
            :placeholder="scope.suggestion ?? '~/Developer'"
            class="rounded-md border border-line bg-transparent p-2"
            data-testid="root-path"
          />
        </label>
        <p class="text-sm text-muted">{{ t('sessions.passkey_note') }}</p>
        <div>
          <Button type="submit" :disabled="busy" data-testid="add-button">
            {{ t('sessions.add_button') }}
          </Button>
        </div>
      </form>
    </section>
  </section>
</template>
