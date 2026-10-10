<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import RepositoryBrowser from '@/areas/projects/RepositoryBrowser.vue'
import { FIELD } from '@/areas/projects/fieldClasses'
import { useFailureMessage } from '@/areas/auth/useFailureMessage'
import { useStepUp } from '@/auth'
import { Button, Mono } from '@/ui'

import {
  excludeFolder,
  loadScope,
  saveLists,
  scanNow,
  type Change,
  type FoundProject,
  type Scope,
} from './scan'

const PURPOSE = 'session_scan:roots'
// Below this width the panel starts as one summary line that opens on tap.
const WIDE = '(min-width: 640px)'

const emit = defineEmits<{ add: [project: FoundProject] }>()
const { t, locale } = useI18n()
const route = useRoute()
const stepUp = useStepUp()
const passkeyMessage = useFailureMessage()

const scope = ref<Scope | null>(null)
const loadFailed = ref(false)
const failure = ref<string | null>(null)
const warnings = ref<string[]>([])
const busy = ref(false)
const scanning = ref(false)
const path = ref('')
const open = ref(typeof matchMedia === 'function' ? matchMedia(WIDE).matches : true)
const panel = ref<HTMLElement | null>(null)

const stored = (rows: Scope['roots']): string[] =>
  rows.filter((r) => r.removable).map((r) => r.path)
const summary = computed(() =>
  scope.value === null || scope.value.machine_wide
    ? t('sessions.machine_wide_short')
    : t('sessions.looking_in', { count: scope.value.roots.length }),
)

function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}

async function scan(): Promise<void> {
  scanning.value = true
  try {
    const fresh = await scanNow()
    if (fresh !== null) scope.value = fresh
    else failure.value = t('sessions.errors.failed')
  } finally {
    scanning.value = false
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
  warnings.value = []
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
    warnings.value = result.warnings
    return true
  } finally {
    busy.value = false
  }
}

async function addFolder(): Promise<void> {
  const wanted = path.value.trim()
  if (wanted === '' || scope.value === null) return
  const roots = [...stored(scope.value.roots), wanted]
  const exclude = stored(scope.value.exclude)
  if (await guarded((credential) => saveLists(roots, exclude, credential))) {
    path.value = ''
    // The first look in the new folder runs once, now that the owner confirmed it.
    await scan()
  }
}

async function removeRoot(root: string): Promise<void> {
  if (scope.value === null) return
  const roots = stored(scope.value.roots).filter((r) => r !== root)
  const exclude = stored(scope.value.exclude)
  await guarded((credential) => saveLists(roots, exclude, credential))
}

async function removeExclusion(folder: string): Promise<void> {
  if (scope.value === null) return
  const roots = stored(scope.value.roots)
  const exclude = stored(scope.value.exclude).filter((e) => e !== folder)
  await guarded((credential) => saveLists(roots, exclude, credential))
}

function notInterested(project: FoundProject): Promise<boolean> {
  return guarded((credential) => excludeFolder(project.path, credential))
}

onMounted(async () => {
  scope.value = await loadScope()
  loadFailed.value = scope.value === null
  if (route.query.panel === 'scan') {
    open.value = true
    panel.value?.scrollIntoView?.({ block: 'start' })
  }
  const loaded = scope.value
  if (loaded !== null && !loaded.machine_wide && loaded.scan.scanned_at === null) await scan()
})
</script>

<template>
  <section ref="panel" class="flex flex-col gap-4" data-testid="session-scan">
    <div class="glass flex flex-col gap-4 rounded-xl border border-line p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-lg font-semibold">{{ t('sessions.title') }}</h2>
        <button
          type="button"
          class="text-sm text-muted underline"
          :aria-expanded="open"
          data-testid="scan-toggle"
          @click="open = !open"
        >
          {{ summary }}
        </button>
      </div>

      <p v-if="loadFailed" role="alert" class="text-status-failed">
        {{ t('sessions.load_failed') }}
      </p>
      <p v-if="failure" role="alert" class="text-status-failed" data-testid="sessions-failure">
        {{ failure }}
      </p>
      <p
        v-for="warning in warnings"
        :key="warning"
        class="text-status-waiting"
        data-testid="sessions-warning"
      >
        {{ warning }}
      </p>

      <div v-if="open && scope !== null" class="flex flex-col gap-4" data-testid="scan-body">
        <p class="text-sm text-muted">{{ t('sessions.lead') }}</p>
        <p v-if="scope.machine_wide" class="text-muted" data-testid="machine-wide">
          {{ t('sessions.machine_wide') }}
        </p>
        <ul v-else class="flex flex-col gap-2" data-testid="roots">
          <li
            v-for="root in scope.roots"
            :key="root.path"
            :data-testid="`root-${root.path}`"
            class="flex flex-wrap items-center justify-between gap-3"
          >
            <Mono class="min-w-0 break-all">{{ root.path }}</Mono>
            <Button
              v-if="root.removable"
              size="sm"
              variant="outline"
              :disabled="busy"
              @click="removeRoot(root.path)"
            >
              {{ t('sessions.remove') }}
            </Button>
            <span v-else class="text-xs text-muted">{{ t('sessions.from_environment') }}</span>
          </li>
        </ul>

        <div v-if="scope.exclude.length > 0" class="flex flex-col gap-2" data-testid="excluded">
          <h3 class="text-sm font-medium">{{ t('sessions.excluded') }}</h3>
          <ul class="flex flex-col gap-2">
            <li
              v-for="folder in scope.exclude"
              :key="folder.path"
              class="flex flex-wrap items-center justify-between gap-3"
            >
              <Mono class="min-w-0 break-all">{{ folder.path }}</Mono>
              <Button
                v-if="folder.removable"
                size="sm"
                variant="outline"
                :disabled="busy"
                @click="removeExclusion(folder.path)"
              >
                {{ t('sessions.remove') }}
              </Button>
            </li>
          </ul>
        </div>

        <form class="flex flex-col gap-2" data-testid="add-root" @submit.prevent="addFolder">
          <label class="flex flex-col gap-1.5 text-sm font-medium">
            {{ t('sessions.add') }}
            <input
              v-model="path"
              :class="[FIELD, 'font-mono']"
              type="text"
              autocomplete="off"
              spellcheck="false"
              :placeholder="scope.suggestion ?? '~/Developer'"
              data-testid="root-path"
            />
          </label>
          <RepositoryBrowser :query="path" @selected="path = $event" @suggested="() => undefined" />
          <p class="text-sm text-muted">{{ t('sessions.passkey_note') }}</p>
          <div>
            <Button type="submit" :disabled="busy" data-testid="add-button">
              {{ t('sessions.add_button') }}
            </Button>
          </div>
        </form>

        <div class="flex flex-wrap items-center gap-3" data-testid="scan-status">
          <Button
            variant="outline"
            size="sm"
            :disabled="scanning"
            data-testid="scan-now"
            @click="scan"
          >
            {{ scanning ? t('sessions.scanning') : t('sessions.scan_now') }}
          </Button>
          <span v-if="scope.scan.scanned_at" class="text-sm text-muted">
            {{ t('sessions.last_scan', { date: when(scope.scan.scanned_at) }) }}
            ·
            <span data-testid="left-out">{{
              t('sessions.left_out', { count: scope.scan.left_out })
            }}</span>
          </span>
          <span v-else class="text-sm text-muted">{{ t('sessions.not_scanned') }}</span>
        </div>
        <p
          v-if="scope.scan.capped"
          role="status"
          class="text-sm text-status-waiting"
          data-testid="capped"
        >
          {{ t('sessions.capped', { count: scope.scan.folders_visited }) }}
        </p>
      </div>
    </div>

    <div
      v-if="scope !== null && scope.scan.found.length > 0"
      class="glass flex flex-col gap-3 rounded-xl border border-line p-4"
      data-testid="found"
    >
      <h2 class="text-lg font-semibold">{{ t('sessions.found_title') }}</h2>
      <p class="text-sm text-muted">{{ t('sessions.found_lead') }}</p>
      <ul class="flex flex-col gap-3">
        <li
          v-for="project in scope.scan.found"
          :key="project.path"
          :data-testid="`found-${project.name}`"
          class="flex flex-wrap items-center justify-between gap-3"
        >
          <div class="flex min-w-0 flex-col">
            <span class="font-medium">{{ project.name }}</span>
            <Mono class="break-all text-xs text-muted">{{ project.relative }}</Mono>
            <span class="text-xs text-muted">
              {{ project.markers.join(', ') }}
              <template v-if="project.last_commit_at">
                · {{ t('sessions.last_commit', { date: when(project.last_commit_at) }) }}
              </template>
            </span>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button size="sm" data-testid="found-add" @click="emit('add', project)">
              {{ t('sessions.add_project') }}
            </Button>
            <Button
              size="sm"
              variant="outline"
              :disabled="busy"
              data-testid="found-skip"
              @click="notInterested(project)"
            >
              {{ t('sessions.not_interested') }}
            </Button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>
