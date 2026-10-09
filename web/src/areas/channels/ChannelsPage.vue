<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useFailureMessage } from '@/areas/auth/useFailureMessage'
import { useStepUp } from '@/auth'
import { authClient } from '@/auth/client'
import { Button, Mono } from '@/ui'

import {
  addChannel,
  removeChannel,
  switchChannel,
  testChannel,
  type Change,
  type Channel,
  type ChannelKind,
} from './channels'

const { t, locale } = useI18n()
const stepUp = useStepUp()
const passkeyMessage = useFailureMessage()

const channels = ref<Channel[]>([])
const kinds = ref<ChannelKind[]>([])
const loaded = ref(false)
const loadFailed = ref(false)
const failure = ref<string | null>(null)
const busy = ref(false)
// The result of the last test the owner asked for, by channel id; null means it arrived.
const tested = ref<Record<number, string | null>>({})

const kind = ref('ntfy')
const name = ref('')
const values = ref<Record<string, string>>({})
const selected = computed(() => kinds.value.find((k) => k.kind === kind.value))

function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}

function resetValues(): void {
  values.value = Object.fromEntries(
    (selected.value?.fields ?? []).map((f) => [f.name, f.default ?? '']),
  )
}

async function load(): Promise<void> {
  const [list, available] = await Promise.all([
    authClient().GET('/api/channels'),
    authClient().GET('/api/channels/kinds'),
  ])
  loadFailed.value = list.data === undefined || available.data === undefined
  if (list.data !== undefined) channels.value = list.data
  if (available.data !== undefined) kinds.value = available.data
  resetValues()
  loaded.value = true
}

function show(change: Change<unknown> & { ok: false }): void {
  failure.value = t(`channels.errors.${change.failure}`)
}

/** Run one change that needs a passkey: ask for it now, when the button is pressed. */
async function guarded(
  purpose: string,
  run: (
    credential: NonNullable<Awaited<ReturnType<typeof stepUp.requestAssertion>>>,
  ) => Promise<void>,
): Promise<void> {
  if (busy.value) return
  busy.value = true
  failure.value = null
  try {
    const credential = await stepUp.requestAssertion(purpose)
    if (credential === null) {
      failure.value = passkeyMessage(stepUp.failure.value ?? 'rejected')
      return
    }
    await run(credential)
  } finally {
    busy.value = false
  }
}

function add(): Promise<void> {
  return guarded('channel:new', async (credential) => {
    const result = await addChannel(kind.value, name.value, values.value, credential)
    if (!result.ok) return show(result)
    channels.value = [...channels.value, result.value.channel]
    tested.value[result.value.channel.id] = result.value.error
    name.value = ''
    resetValues()
  })
}

function toggle(channel: Channel): Promise<void> {
  return guarded(`channel:${channel.id}`, async (credential) => {
    const result = await switchChannel(channel.id, !channel.enabled, credential)
    if (!result.ok) return show(result)
    channels.value = channels.value.map((c) => (c.id === channel.id ? result.value : c))
  })
}

function remove(channel: Channel): Promise<void> {
  return guarded(`channel:${channel.id}`, async (credential) => {
    const result = await removeChannel(channel.id, credential)
    if (!result.ok) return show(result)
    channels.value = channels.value.filter((c) => c.id !== channel.id)
  })
}

async function test(channel: Channel): Promise<void> {
  failure.value = null
  const result = await testChannel(channel.id)
  if (!result.ok) return show(result)
  tested.value[channel.id] = result.value.error
  channels.value = channels.value.map((c) => (c.id === channel.id ? result.value.channel : c))
}

onMounted(load)
</script>

<template>
  <section class="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-8">
    <header class="flex flex-col gap-2">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('channels.title') }}</h1>
      <p class="text-muted">{{ t('channels.lead') }}</p>
    </header>

    <p v-if="loadFailed" role="alert" class="text-status-failed">{{ t('channels.load_failed') }}</p>
    <p v-if="failure" role="alert" class="text-status-failed" data-testid="channels-failure">
      {{ failure }}
    </p>
    <p v-if="!loaded" class="text-muted">{{ t('channels.loading') }}</p>
    <p v-else-if="channels.length === 0 && !loadFailed" class="text-muted">
      {{ t('channels.empty') }}
    </p>

    <ul class="flex flex-col gap-4" data-testid="channel-list">
      <li
        v-for="channel in channels"
        :key="channel.id"
        :data-testid="`channel-${channel.id}`"
        :data-enabled="channel.enabled"
        class="glass flex min-w-0 flex-col gap-3 rounded-xl border border-line p-4"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="flex min-w-0 flex-col gap-1">
            <h2 class="text-lg font-medium break-words">{{ channel.name }}</h2>
            <p class="flex flex-wrap items-center gap-x-2 text-sm text-muted">
              <Mono>{{ channel.kind }}</Mono>
              <span v-if="!channel.enabled" data-testid="channel-disabled">
                · {{ t('channels.disabled') }}
              </span>
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              :data-testid="`test-${channel.id}`"
              @click="test(channel)"
            >
              {{ t('channels.test') }}
            </Button>
            <Button
              variant="outline"
              size="sm"
              :disabled="busy"
              :data-testid="`toggle-${channel.id}`"
              @click="toggle(channel)"
            >
              {{ channel.enabled ? t('channels.disable') : t('channels.enable') }}
            </Button>
            <Button
              variant="outline"
              size="sm"
              :disabled="busy"
              :data-testid="`remove-${channel.id}`"
              @click="remove(channel)"
            >
              {{ t('channels.remove') }}
            </Button>
          </div>
        </div>
        <p
          v-if="channel.last_tested_at"
          class="text-sm"
          :class="channel.last_test_ok ? 'text-muted' : 'text-status-failed'"
          :data-testid="`result-${channel.id}`"
          :data-ok="channel.last_test_ok"
        >
          {{
            channel.last_test_ok
              ? t('channels.test_ok', { date: when(channel.last_tested_at) })
              : t('channels.test_failed', {
                  date: when(channel.last_tested_at),
                  reason: channel.last_test_error ?? '',
                })
          }}
        </p>
        <p v-else class="text-sm text-muted">{{ t('channels.untested') }}</p>
      </li>
    </ul>

    <form
      class="glass flex flex-col gap-3 rounded-xl border border-line p-4"
      data-testid="channel-form"
      @submit.prevent="add"
    >
      <h2 class="text-lg font-medium">{{ t('channels.add') }}</h2>
      <label class="flex flex-col gap-1 text-sm">
        {{ t('channels.kind') }}
        <select
          v-model="kind"
          class="rounded-md border border-line bg-transparent p-2"
          data-testid="kind"
          @change="resetValues"
        >
          <option v-for="k in kinds" :key="k.kind" :value="k.kind" :disabled="!k.available">
            {{ k.label }}{{ k.available ? '' : ` (${t('channels.not_set_up')})` }}
          </option>
        </select>
      </label>
      <label class="flex flex-col gap-1 text-sm">
        {{ t('channels.name') }}
        <input
          v-model="name"
          required
          maxlength="64"
          class="rounded-md border border-line bg-transparent p-2"
          data-testid="name"
        />
      </label>
      <label
        v-for="field in selected?.fields ?? []"
        :key="field.name"
        class="flex flex-col gap-1 text-sm"
      >
        {{ field.label }}
        <input
          v-model="values[field.name]"
          :type="field.secret ? 'password' : 'text'"
          :autocomplete="field.secret ? 'off' : undefined"
          required
          class="rounded-md border border-line bg-transparent p-2"
          :data-testid="`field-${field.name}`"
        />
      </label>
      <p class="text-sm text-muted">{{ t('channels.passkey_note') }}</p>
      <div>
        <Button type="submit" :disabled="busy" data-testid="add">{{
          t('channels.add_button')
        }}</Button>
      </div>
    </form>
  </section>
</template>
