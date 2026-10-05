<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api } from '@/api'
import { Button } from '@/ui'

import { errorKey } from './authoringErrors'
import { FIELD, LABEL } from './fieldClasses'
import { usdToMicros } from './usd'
import RepositoryBrowser from './RepositoryBrowser.vue'

type Folder = { name: string; path: string }

const emit = defineEmits<{ added: [projectId: number]; cancel: [] }>()
const { t } = useI18n()

const name = ref('')
const repoPath = ref('')
const budget = ref('')
const busy = ref(false)
const failure = ref<string | null>(null)
const choosing = ref(false)
const suggestions = ref<Folder[]>([])
const pathEdited = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchVersion = 0

function search(query: string, fromName: boolean): void {
  clearTimeout(searchTimer)
  const version = ++searchVersion
  suggestions.value = []
  if (query.trim().length < 2) return
  searchTimer = setTimeout(async () => {
    try {
      const { data } = await api.GET('/api/repository-browser/suggest', {
        params: { query: { query: query.trim() } },
      })
      if (version !== searchVersion || !data) return
      suggestions.value = data
      if (fromName && !pathEdited.value) {
        const exact = data.filter(
          (folder) => folder.name.toLowerCase() === query.trim().toLowerCase(),
        )
        const match = exact.length === 1 ? exact[0] : data.length === 1 ? data[0] : null
        if (match) repoPath.value = match.path
      }
    } catch {
      if (version === searchVersion) suggestions.value = []
    }
  }, 250)
}

watch(name, (value) => {
  if (!pathEdited.value) {
    repoPath.value = ''
    search(value, true)
  }
})

function pathInput(): void {
  pathEdited.value = true
  search(repoPath.value, false)
}

function selectRepository(path: string): void {
  repoPath.value = path
  pathEdited.value = true
  suggestions.value = []
  choosing.value = false
}

onBeforeUnmount(() => clearTimeout(searchTimer))

async function submit(): Promise<void> {
  if (busy.value) return
  const micros = usdToMicros(budget.value)
  if (micros === undefined) {
    failure.value = 'projects.errors.budget'
    return
  }
  busy.value = true
  failure.value = null
  try {
    const { data, error } = await api.POST('/api/projects', {
      body: { name: name.value.trim(), repo_path: repoPath.value.trim(), budget_micros: micros },
    })
    if (data) emit('added', data.id)
    else failure.value = errorKey(error)
  } catch {
    failure.value = 'projects.errors.network'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form
    class="glass flex flex-col gap-4 rounded-xl border border-line p-5"
    data-testid="add-project-form"
    @submit.prevent="submit"
  >
    <h2 class="text-lg font-semibold">{{ t('projects.add.title') }}</h2>
    <label :class="LABEL">
      {{ t('projects.add.name') }}
      <input v-model="name" :class="FIELD" required maxlength="120" name="name" />
    </label>
    <label :class="LABEL">
      {{ t('projects.add.repo') }}
      <input
        v-model="repoPath"
        :class="[FIELD, 'font-mono']"
        required
        name="repo_path"
        placeholder="/home/you/code/site"
        autocomplete="off"
        spellcheck="false"
        @input="pathInput"
      />
    </label>
    <span class="-mt-3 text-xs text-muted">{{ t('projects.add.repoHint') }}</span>
    <ul
      v-if="suggestions.length"
      class="max-h-48 overflow-y-auto rounded border border-line"
      data-testid="path-suggestions"
    >
      <li v-for="folder in suggestions" :key="folder.path">
        <button
          type="button"
          class="w-full break-all px-3 py-2 text-left font-mono text-sm hover:bg-surface-raised"
          @click="selectRepository(folder.path)"
        >
          {{ folder.path }}
        </button>
      </li>
    </ul>
    <Button type="button" variant="outline" class="self-start" @click="choosing = !choosing">
      {{ t('projects.add.browse') }}
    </Button>
    <RepositoryBrowser v-if="choosing" @selected="selectRepository" @close="choosing = false" />
    <label :class="LABEL">
      {{ t('projects.add.budget') }}
      <input
        v-model="budget"
        :class="[FIELD, 'font-mono']"
        inputmode="decimal"
        name="budget"
        placeholder="25"
        autocomplete="off"
      />
      <span class="text-xs font-normal text-muted">{{ t('projects.add.budgetHint') }}</span>
    </label>
    <p v-if="failure" role="alert" class="text-sm text-status-failed" data-testid="form-error">
      {{ t(failure) }}
    </p>
    <div class="flex flex-wrap gap-3">
      <Button type="submit" :disabled="busy" data-testid="add-project-submit">
        {{ busy ? t('projects.add.working') : t('projects.add.submit') }}
      </Button>
      <Button type="button" variant="outline" :disabled="busy" @click="emit('cancel')">
        {{ t('projects.add.cancel') }}
      </Button>
    </div>
  </form>
</template>
