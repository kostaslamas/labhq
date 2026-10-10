<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { Button, Mono } from '@/ui'

import ProjectSessions from './ProjectSessions.vue'
import {
  createFolderManager,
  loadSessions,
  scanSessions,
  type Outcome,
  type SessionsView,
} from './sessions'

const { t, locale } = useI18n()
const view = ref<SessionsView | null>(null)
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const scanning = ref(false)
const folderResult = ref<Outcome | null>(null)

function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}

async function load(): Promise<void> {
  view.value = await loadSessions()
  state.value = view.value === null ? 'failed' : 'ready'
}

async function scan(): Promise<void> {
  scanning.value = true
  try {
    const fresh = await scanSessions()
    if (fresh === null) state.value = 'failed'
    else {
      view.value = fresh
      state.value = 'ready'
    }
  } finally {
    scanning.value = false
  }
}

async function manage(folder: string): Promise<void> {
  folderResult.value = await createFolderManager(folder)
}

// A server that has not scanned since it started has nothing to show; looking is free.
onMounted(async () => {
  await load()
  if (view.value !== null && view.value.scanned_at === null) await scan()
})
</script>

<template>
  <section class="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-8">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-col gap-1">
        <h1 class="text-2xl font-semibold tracking-wide">{{ t('sessions.nav') }}</h1>
        <p class="text-sm text-muted" data-testid="last-scan">
          <template v-if="view?.scanned_at">
            {{ t('sessions.last_scan', { date: when(view.scanned_at) }) }}
            · {{ t('sessions.left_out', { count: view.left_out }) }}
          </template>
          <template v-else>{{ t('sessions.not_scanned') }}</template>
        </p>
      </div>
      <Button :disabled="scanning" data-testid="scan-now-sessions" @click="scan">
        {{ scanning ? t('sessions.scanning') : t('sessions.scan_now') }}
      </Button>
    </header>

    <p v-if="state === 'failed'" role="alert" class="text-status-failed">
      {{ t('sessions.load_failed') }}
    </p>
    <p v-else-if="state === 'loading'" class="text-muted">{{ t('sessions.loading') }}</p>

    <template v-else-if="view">
      <ul v-if="view.tools.length" class="flex flex-wrap gap-2 text-xs" data-testid="tools">
        <li
          v-for="tool in view.tools"
          :key="tool.tool"
          class="rounded-md border border-line px-2 py-1"
        >
          {{ tool.tool }}:
          {{
            tool.logged_in === null
              ? t('sessions.login.unknown')
              : tool.logged_in
                ? t('sessions.login.in')
                : t('sessions.login.out')
          }}
          <template v-if="tool.plan"> · {{ tool.plan }} ({{ tool.plan_used_percent }}%)</template>
        </li>
      </ul>

      <p
        v-if="view.projects.length === 0"
        class="glass rounded-xl border border-line p-6 text-muted"
      >
        {{ view.scanned_at ? t('sessions.none') : t('sessions.scan_hint') }}
      </p>
      <ul v-else class="flex flex-col gap-4" data-testid="scanned-projects">
        <ProjectSessions v-for="project in view.projects" :key="project.root" :project="project" />
      </ul>

      <section
        v-if="view.folders.length"
        class="flex flex-col gap-3"
        data-testid="folder-proposals"
      >
        <h2 class="text-lg font-semibold">{{ t('sessions.folders.title') }}</h2>
        <p class="text-sm text-muted">{{ t('sessions.folders.lead') }}</p>
        <ul class="flex flex-col gap-2">
          <li
            v-for="folder in view.folders"
            :key="folder.folder"
            class="flex flex-wrap items-center justify-between gap-3"
          >
            <span class="flex min-w-0 flex-col">
              <Mono class="break-all">{{ folder.folder }}</Mono>
              <span class="text-xs text-muted">
                {{ t('sessions.folders.count', { count: folder.projects.length }) }}
              </span>
            </span>
            <Button
              size="sm"
              variant="outline"
              data-testid="folder-manager"
              @click="manage(folder.folder)"
            >
              {{ t('sessions.folders.create') }}
            </Button>
          </li>
        </ul>
        <p v-if="folderResult?.ok" role="status" class="text-sm" data-testid="folder-result">
          {{ folderResult.requested.summary }}
          <RouterLink :to="{ name: 'approvals' }" class="text-accent underline">
            {{ t('sessions.review', { id: folderResult.requested.approval_id }) }}
          </RouterLink>
        </p>
        <p v-else-if="folderResult" role="alert" class="text-sm text-status-failed">
          {{ folderResult.message }}
        </p>
      </section>
    </template>
  </section>
</template>
