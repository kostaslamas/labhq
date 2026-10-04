<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, isErrorEnvelope, uiState, type components } from '@/api'
import { useLiveTopic } from '@/live'
import { StatusBadge } from '@/status'
import { Button, Mono } from '@/ui'

import { avatarHue, formatInstant, initials } from './format'

type Meeting = components['schemas']['MeetingDetail']

// The owner may write while the meeting waits for approval or runs (labhq.meetings.transcript).
const OPEN = new Set(['requested', 'running'])

const props = defineProps<{ id: number }>()
const { t, locale } = useI18n()

const meeting = ref<Meeting | null>(null)
const missing = ref(false)
const failed = ref(false)
const draft = ref('')
const sending = ref(false)
const joinFailed = ref(false)

const open = computed(() => meeting.value !== null && OPEN.has(meeting.value.status))

async function load(): Promise<void> {
  const { data, response } = await api.GET('/api/meetings/{meeting_id}', {
    params: { path: { meeting_id: props.id } },
  })
  missing.value = response.status === 404
  failed.value = data === undefined && !missing.value
  if (data) meeting.value = data
}

async function join(): Promise<void> {
  const text = draft.value.trim()
  if (!text || sending.value) return
  sending.value = true
  joinFailed.value = false
  const { error } = await api.POST('/api/meetings/{meeting_id}/messages', {
    params: { path: { meeting_id: props.id } },
    body: { text },
  })
  sending.value = false
  if (error !== undefined) {
    joinFailed.value = true
    // A closed meeting changed under us; show it as it is now.
    if (isErrorEnvelope(error)) await load()
    return
  }
  draft.value = ''
  await load()
}

onMounted(load)
useLiveTopic('meetings', load)
</script>

<template>
  <section class="mx-auto flex min-w-0 max-w-5xl flex-col gap-6 p-4 sm:p-8">
    <RouterLink :to="{ name: 'meetings' }" class="text-sm text-muted hover:text-foreground">
      ← {{ t('meetings.nav') }}
    </RouterLink>
    <p v-if="missing" role="alert" class="text-status-failed">{{ t('meetings.missing') }}</p>
    <p v-else-if="failed" role="alert" class="text-status-failed">{{ t('meetings.failed') }}</p>

    <template v-if="meeting">
      <header class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex min-w-0 flex-col gap-1">
          <h1 class="text-2xl font-semibold tracking-wide [overflow-wrap:anywhere]">
            {{ meeting.kind }} · {{ meeting.project_name }}
          </h1>
          <p class="text-sm text-muted">
            <Mono>#{{ meeting.id }}</Mono>
            ·
            {{
              meeting.started_at
                ? formatInstant(locale, meeting.started_at)
                : t('meetings.not_started')
            }}
            <template v-if="meeting.channel">
              · {{ t('meetings.channel', { name: meeting.channel }) }}
            </template>
          </p>
        </div>
        <StatusBadge
          :state="uiState('meeting_status', meeting.status)"
          data-testid="meeting-status"
        />
      </header>

      <section
        class="glass flex flex-col gap-2 rounded-xl border border-line p-4"
        data-testid="agenda"
      >
        <h2 class="text-lg font-medium">{{ t('meetings.agenda') }}</h2>
        <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ meeting.agenda }}</p>
        <ul class="flex flex-wrap gap-2" data-testid="participants">
          <li
            v-for="participant in meeting.participants"
            :key="participant.id"
            class="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted"
          >
            {{ participant.name }}
          </li>
        </ul>
      </section>

      <section class="flex flex-col gap-3">
        <h2 class="text-lg font-medium">{{ t('meetings.conversation') }}</h2>
        <p v-if="meeting.messages.length === 0" class="text-muted">
          {{ t('meetings.no_messages') }}
        </p>
        <ol class="flex min-w-0 flex-col gap-3" data-testid="transcript">
          <li
            v-for="message in meeting.messages"
            :key="message.id"
            :data-source="message.source"
            class="flex min-w-0 gap-3"
            data-testid="message"
          >
            <span
              class="flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
              :class="message.source === 'owner' ? 'bg-accent text-foreground' : 'text-background'"
              :style="
                message.agent_id !== null
                  ? { backgroundColor: `hsl(${avatarHue(message.agent_id)} 55% 65%)` }
                  : undefined
              "
              aria-hidden="true"
              data-testid="avatar"
            >
              {{ initials(message.speaker) }}
            </span>
            <div class="glass min-w-0 flex-1 rounded-xl border border-line p-3">
              <p class="flex flex-wrap items-baseline gap-x-2 text-sm">
                <span class="font-medium" data-testid="speaker">{{ message.speaker }}</span>
                <span class="text-xs text-muted">
                  {{ formatInstant(locale, message.created_at, { timeStyle: 'short' }) }}
                </span>
              </p>
              <p class="whitespace-pre-wrap [overflow-wrap:anywhere]" data-testid="message-text">
                {{ message.text }}
              </p>
            </div>
          </li>
        </ol>

        <form v-if="open" class="flex flex-col gap-2" data-testid="join" @submit.prevent="join">
          <label for="join-text" class="text-sm text-muted">{{ t('meetings.join_label') }}</label>
          <textarea
            id="join-text"
            v-model="draft"
            rows="3"
            maxlength="4000"
            class="w-full rounded-xl border border-line bg-transparent p-3"
            data-testid="join-text"
          />
          <p v-if="joinFailed" role="alert" class="text-sm text-status-failed">
            {{ t('meetings.join_failed') }}
          </p>
          <Button type="submit" class="self-start" :disabled="sending" data-testid="join-send">
            {{ t('meetings.join_send') }}
          </Button>
        </form>
        <p v-else class="text-sm text-muted">{{ t('meetings.closed') }}</p>
      </section>

      <section class="glass flex flex-col gap-2 rounded-xl border border-line p-4">
        <h2 class="text-lg font-medium">{{ t('meetings.decisions') }}</h2>
        <p v-if="meeting.decisions.length === 0" class="text-muted">
          {{ t('meetings.no_decisions') }}
        </p>
        <ol class="flex list-decimal flex-col gap-1 pl-5" data-testid="decisions">
          <li
            v-for="decision in meeting.decisions"
            :key="decision.id"
            class="[overflow-wrap:anywhere]"
          >
            {{ decision.text }}
          </li>
        </ol>
      </section>

      <section class="glass flex flex-col gap-2 rounded-xl border border-line p-4">
        <h2 class="text-lg font-medium">{{ t('meetings.action_items') }}</h2>
        <p v-if="meeting.action_items.length === 0" class="text-muted">
          {{ t('meetings.no_actions') }}
        </p>
        <ul class="flex flex-col gap-2" data-testid="action-items">
          <li
            v-for="item in meeting.action_items"
            :key="item.id"
            class="flex flex-wrap items-center justify-between gap-2"
          >
            <div class="flex min-w-0 flex-col">
              <span class="[overflow-wrap:anywhere]">{{ item.text }}</span>
              <span v-if="item.assignee_name" class="text-sm text-muted">{{
                item.assignee_name
              }}</span>
            </div>
            <div class="flex items-center gap-2">
              <StatusBadge :state="uiState('task_status', item.task_status)" />
              <RouterLink
                :to="{ name: 'projects', query: { task: item.task_id } }"
                class="text-sm underline"
                :data-testid="`task-link-${item.task_id}`"
              >
                {{ t('meetings.task') }} <Mono>#{{ item.task_id }}</Mono>
              </RouterLink>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>
