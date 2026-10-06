<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, isErrorEnvelope, type components } from '@/api'
import { useLiveTopic } from '@/live'
import { Button } from '@/ui'

import ReportCard from './ReportCard.vue'

type Turn = components['schemas']['CeoChatTurn']
type Report = components['schemas']['CeoReportOut']
type Entry =
  | { key: string; at: number; turn: Turn; report?: never }
  | { key: string; at: number; report: Report; turn?: never }

const { t, locale } = useI18n()
const turns = ref<Turn[]>([])
const reports = ref<Report[]>([])
const configured = ref<boolean | null>(null)
const loading = ref(true)
const loadFailed = ref(false)
const draft = ref('')
const sending = ref(false)
const sendFailure = ref('')
const waiting = computed(() =>
  turns.value.some((turn) => ['queued', 'running'].includes(turn.status)),
)
// Reports sit between the turns by time, so the conversation reads in order.
const timeline = computed<Entry[]>(() =>
  [
    ...turns.value.map((turn) => ({
      key: `turn-${turn.id}`,
      at: Date.parse(turn.created_at),
      turn,
    })),
    ...reports.value.map((report) => ({
      key: `report-${report.id}`,
      at: Date.parse(report.created_at),
      report,
    })),
  ].sort((a, b) => a.at - b.at),
)
let refreshTimer: ReturnType<typeof setInterval> | undefined

function time(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}

async function load(): Promise<void> {
  const [assignment, messages, reported] = await Promise.all([
    api.GET('/api/org/ceo'),
    api.GET('/api/org/ceo/messages'),
    api.GET('/api/org/ceo/reports'),
  ])
  if (!assignment.data || !messages.data || !reported.data) {
    loadFailed.value = true
  } else {
    configured.value = assignment.data.id !== null
    turns.value = messages.data
    reports.value = reported.data
    loadFailed.value = false
  }
  loading.value = false
}

async function send(): Promise<void> {
  const text = draft.value.trim()
  if (!text || sending.value || waiting.value || !configured.value) return
  sending.value = true
  sendFailure.value = ''
  try {
    const { data, error } = await api.POST('/api/org/ceo/messages', { body: { text } })
    if (data) {
      turns.value = [...turns.value, data]
      draft.value = ''
    } else {
      const code = isErrorEnvelope(error) ? error.error.code : ''
      sendFailure.value =
        code === 'ceo_budget_stop'
          ? 'ceo.budgetStop'
          : code === 'ceo_inactive'
            ? 'ceo.inactive'
            : 'ceo.sendFailed'
      await load()
    }
  } catch {
    sendFailure.value = 'ceo.sendFailed'
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  void load()
  refreshTimer = setInterval(() => {
    if (waiting.value) void load()
  }, 3000)
})
onUnmounted(() => clearInterval(refreshTimer))
useLiveTopic('runs', load)
useLiveTopic('tasks', load)
</script>

<template>
  <section class="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-8" data-testid="ceo-chat">
    <header class="flex flex-col gap-1">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('ceo.title') }}</h1>
      <p class="text-sm text-muted">{{ t('ceo.hint') }}</p>
    </header>

    <p v-if="loading" class="text-muted">{{ t('ceo.nav') }}…</p>
    <p v-else-if="loadFailed" role="alert" class="text-status-failed">
      {{ t('ceo.loadFailed') }}
    </p>
    <div v-else-if="!configured" class="glass rounded-xl border border-line p-5">
      <p>{{ t('ceo.setup') }}</p>
      <RouterLink :to="{ name: 'projects' }" class="mt-3 inline-block text-accent underline">
        {{ t('ceo.setupLink') }}
      </RouterLink>
    </div>

    <template v-else>
      <p v-if="timeline.length === 0" class="glass rounded-xl border border-line p-5 text-muted">
        {{ t('ceo.empty') }}
      </p>
      <ol v-else class="flex flex-col gap-5" data-testid="ceo-transcript">
        <li v-for="entry in timeline" :key="entry.key" class="flex flex-col gap-3">
          <ReportCard v-if="entry.report" :report="entry.report" @decided="load" />
          <template v-else-if="entry.turn">
            <div
              class="glass ml-6 rounded-xl border border-line p-4 sm:ml-16"
              data-testid="ceo-owner-message"
            >
              <p class="mb-2 text-xs text-muted">
                {{ t('ceo.you') }} · {{ time(entry.turn.created_at) }}
              </p>
              <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ entry.turn.text }}</p>
            </div>
            <div
              class="glass mr-6 rounded-xl border border-line p-4 sm:mr-16"
              data-testid="ceo-reply"
            >
              <p class="mb-2 text-xs text-muted">{{ t('ceo.ceo') }}</p>
              <p v-if="entry.turn.reply" class="whitespace-pre-wrap [overflow-wrap:anywhere]">
                {{ entry.turn.reply }}
              </p>
              <p
                v-else
                class="text-sm text-muted"
                :class="entry.turn.status === 'failed' ? 'text-status-failed' : ''"
              >
                {{ t(`ceo.${entry.turn.status}`) }}
              </p>
            </div>
          </template>
        </li>
      </ol>

      <form
        class="glass flex flex-col gap-3 rounded-xl border border-line p-5"
        @submit.prevent="send"
      >
        <label for="ceo-message" class="text-sm font-medium">{{ t('ceo.message') }}</label>
        <textarea
          id="ceo-message"
          v-model="draft"
          rows="4"
          maxlength="4000"
          :placeholder="t('ceo.placeholder')"
          class="w-full rounded-xl border border-line bg-transparent p-3"
          data-testid="ceo-message"
        />
        <p v-if="sendFailure" role="alert" class="text-sm text-status-failed">
          {{ t(sendFailure) }}
        </p>
        <Button
          type="submit"
          class="self-start"
          :disabled="sending || waiting || !draft.trim()"
          data-testid="ceo-send"
        >
          {{ sending ? t('ceo.sending') : t('ceo.send') }}
        </Button>
      </form>
    </template>
  </section>
</template>
