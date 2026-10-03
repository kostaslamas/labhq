<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, uiState, type components } from '@/api'
import { useLiveTopic } from '@/live'
import { StatusBadge } from '@/status'
import { Button, Mono } from '@/ui'

import { formatInstant } from './format'

type MeetingItem = components['schemas']['MeetingItem']

const FIRST_PAGE = 50

const { t, locale } = useI18n()

const meetings = ref<MeetingItem[]>([])
const nextCursor = ref<string | null>(null)
const loaded = ref(false)
const failed = ref(false)

// A live change reloads what is on screen from the top, so a new meeting appears first
// and a status change shows without a refresh.
async function load(): Promise<void> {
  const limit = Math.max(meetings.value.length, FIRST_PAGE)
  const { data } = await api.GET('/api/meetings', { params: { query: { limit } } })
  failed.value = data === undefined
  if (data) {
    meetings.value = data.items
    nextCursor.value = data.next_cursor ?? null
  }
  loaded.value = true
}

async function more(): Promise<void> {
  if (!nextCursor.value) return
  const { data } = await api.GET('/api/meetings', {
    params: { query: { cursor: nextCursor.value } },
  })
  if (!data) return
  meetings.value = [...meetings.value, ...data.items]
  nextCursor.value = data.next_cursor ?? null
}

onMounted(load)
useLiveTopic('meetings', load)
</script>

<template>
  <section class="mx-auto flex min-w-0 max-w-5xl flex-col gap-4 p-4 sm:p-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('meetings.nav') }}</h1>
    <p v-if="failed" role="alert" class="text-status-failed">{{ t('meetings.failed') }}</p>
    <p
      v-else-if="loaded && meetings.length === 0"
      class="glass rounded-xl border border-line p-6 text-muted"
    >
      {{ t('meetings.empty') }}
    </p>

    <ul
      v-if="meetings.length > 0"
      class="glass divide-y divide-line rounded-xl border border-line"
      data-testid="meeting-list"
    >
      <li v-for="meeting in meetings" :key="meeting.id">
        <RouterLink
          :to="{ name: 'meeting', params: { id: meeting.id } }"
          class="flex flex-wrap items-center justify-between gap-3 p-4 hover:bg-accent/10"
          data-testid="meeting-row"
        >
          <div class="flex min-w-0 flex-col">
            <span class="font-medium [overflow-wrap:anywhere]">
              {{ meeting.kind }} · {{ meeting.project_name }}
            </span>
            <span class="text-sm text-muted">
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
            </span>
          </div>
          <StatusBadge :state="uiState('meeting_status', meeting.status)" />
        </RouterLink>
      </li>
    </ul>
    <Button v-if="nextCursor" variant="outline" class="self-start" data-testid="more" @click="more">
      {{ t('meetings.more') }}
    </Button>
  </section>
</template>
