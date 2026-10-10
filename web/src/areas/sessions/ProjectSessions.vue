<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button, Mono } from '@/ui'

import {
  analyse,
  closeSession,
  continueSession,
  type Outcome,
  type ScannedProject,
  type ScannedSession,
} from './sessions'

const props = defineProps<{ project: ScannedProject }>()
const { t, locale } = useI18n()
const busy = ref(false)
// What the last action recorded, shown under the project until the next one.
const result = ref<Outcome | null>(null)

function idle(seconds: number | null): string {
  if (seconds === null) return t('sessions.idle.unknown')
  if (seconds < 90) return t('sessions.idle.now')
  const minutes = seconds / 60
  if (minutes < 90) return t('sessions.idle.minutes', { count: Math.round(minutes) })
  const hours = minutes / 60
  if (hours < 48) return t('sessions.idle.hours', { count: Math.round(hours) })
  return t('sessions.idle.days', { count: Math.round(hours / 24) })
}

function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(instant))
}

async function act(run: () => Promise<Outcome>): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    result.value = await run()
  } finally {
    busy.value = false
  }
}

const doContinue = (session: ScannedSession) =>
  act(() => continueSession(props.project.name, session))
const doClose = (session: ScannedSession) =>
  act(() => closeSession(props.project.name, session.pid ?? 0))
const doAnalyse = () => act(() => analyse(props.project.name))
</script>

<template>
  <li
    class="glass flex min-w-0 flex-col gap-3 rounded-xl border border-line p-4"
    :data-testid="`scanned-${project.name}`"
  >
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 flex-col">
        <h3 class="break-words text-lg font-semibold">{{ project.name }}</h3>
        <Mono class="break-all text-xs text-muted">{{ project.root }}</Mono>
        <p class="text-sm text-muted" data-testid="git-facts">
          <template v-if="!project.has_repo">{{ t('sessions.git.none') }}</template>
          <template v-else>
            {{ project.git.branch ?? t('sessions.git.noCommits') }}
            · {{ t('sessions.git.dirty', { count: project.git.dirty_files }) }}
            <template v-if="project.git.last_commit_subject">
              · “{{ project.git.last_commit_subject }}”
              <template v-if="project.git.last_commit_at">
                ({{ when(project.git.last_commit_at) }})
              </template>
            </template>
            <template v-if="project.git.open_pr"> · {{ project.git.open_pr }}</template>
          </template>
        </p>
      </div>
      <Button size="sm" variant="outline" :disabled="busy" data-testid="analyse" @click="doAnalyse">
        {{ t('sessions.analyse') }}
      </Button>
    </div>

    <ul class="flex flex-col gap-2">
      <li
        v-for="(session, index) in project.sessions"
        :key="`${session.tool}-${session.session_id ?? session.pid}-${index}`"
        class="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-2"
        data-testid="session-row"
      >
        <div class="flex min-w-0 flex-col">
          <span class="font-medium">
            {{ session.tool }}
            <Mono class="text-xs text-muted">{{ session.session_id ?? `pid ${session.pid}` }}</Mono>
          </span>
          <span class="text-sm text-muted">
            {{ t(`sessions.state.${session.state}`) }} · {{ idle(session.idle_seconds) }}
          </span>
          <span class="text-xs text-muted" data-testid="proposal">
            {{ t(`sessions.action.${session.proposal.action}`) }} — {{ session.proposal.reason }}
          </span>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button
            size="sm"
            :variant="session.proposal.action === 'continue' ? 'default' : 'outline'"
            :disabled="busy"
            data-testid="continue"
            @click="doContinue(session)"
          >
            {{ session.resumable ? t('sessions.continue') : t('sessions.handoff') }}
          </Button>
          <Button
            v-if="session.pid !== null"
            size="sm"
            :variant="session.proposal.action === 'close' ? 'default' : 'outline'"
            :disabled="busy"
            data-testid="close"
            @click="doClose(session)"
          >
            {{ t('sessions.close') }}
          </Button>
        </div>
      </li>
    </ul>

    <div
      v-if="result"
      role="status"
      class="flex flex-col gap-1 text-sm"
      data-testid="action-result"
    >
      <template v-if="result.ok">
        <p class="whitespace-pre-line" data-testid="action-summary">
          {{ result.requested.summary }}
        </p>
        <RouterLink
          v-if="result.requested.approval_id !== null"
          :to="{ name: 'approvals' }"
          class="w-fit text-accent underline"
          data-testid="approval-link"
        >
          {{ t('sessions.review', { id: result.requested.approval_id }) }}
        </RouterLink>
      </template>
      <p v-else role="alert" class="text-status-failed" data-testid="action-error">
        {{ result.message }}
      </p>
    </div>
  </li>
</template>
