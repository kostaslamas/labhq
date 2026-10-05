<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'

type Listing = components['schemas']['BrowserListing']
type Folder = components['schemas']['BrowserFolder']

const props = defineProps<{ query: string }>()
const emit = defineEmits<{ selected: [path: string]; suggested: [path: string] }>()
const { t } = useI18n()
const roots = ref<Folder[]>([])
const listing = ref<Listing | null>(null)
const matches = ref<Folder[]>([])
const prefix = ref('')
const loading = ref(false)
const failed = ref(false)
const openedPath = ref('')
let requestVersion = 0
let timer: ReturnType<typeof setTimeout> | undefined

const folders = computed(() =>
  (listing.value?.folders ?? []).filter((folder) =>
    folder.name.toLowerCase().startsWith(prefix.value.toLowerCase()),
  ),
)
const visibleRoots = computed(() => {
  const query = props.query.trim()
  if (!query.startsWith('/')) return roots.value
  return roots.value.filter(
    (root) =>
      root.path.startsWith(query) || query === root.path || query.startsWith(root.path + '/'),
  )
})
const currentRoot = computed(() =>
  roots.value.find(
    (root) => listing.value?.path === root.path || listing.value?.path?.startsWith(root.path + '/'),
  ),
)

async function update(query: string, version: number): Promise<void> {
  const typed = query.trim()
  listing.value = null
  matches.value = []
  prefix.value = ''
  if (!typed || !roots.value.length) {
    loading.value = false
    return
  }
  loading.value = true
  failed.value = false
  try {
    if (!typed.startsWith('/')) {
      if (typed.length < 2) return
      const { data } = await api.GET('/api/repository-browser/suggest', {
        params: { query: { query: typed } },
      })
      if (version !== requestVersion) return
      if (!data) {
        failed.value = true
        return
      }
      matches.value = data
      if (data.length === 1) emit('suggested', data[0]!.path)
      return
    }
    const root = roots.value.find(
      (root) => typed === root.path || typed.startsWith(root.path + '/'),
    )
    if (!root) return
    const showChildren = typed === root.path || typed.endsWith('/') || typed === openedPath.value
    const path = showChildren ? typed.replace(/\/$/, '') : typed.slice(0, typed.lastIndexOf('/'))
    const filter = showChildren ? '' : typed.slice(typed.lastIndexOf('/') + 1)
    const { data } = await api.GET('/api/repository-browser', {
      params: { query: { path } },
    })
    if (version !== requestVersion) return
    if (data) {
      listing.value = data
      prefix.value = filter
    }
  } catch {
    if (version === requestVersion) failed.value = true
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function schedule(query: string): void {
  clearTimeout(timer)
  const version = ++requestVersion
  if (query !== openedPath.value) openedPath.value = ''
  loading.value = Boolean(query.trim())
  timer = setTimeout(() => void update(query, version), 180)
}

function choose(path: string): void {
  openedPath.value = path
  emit('selected', path)
  schedule(path)
}

onMounted(async () => {
  try {
    const { data } = await api.GET('/api/repository-browser', { params: { query: {} } })
    if (data) roots.value = data.roots
    else failed.value = true
  } catch {
    failed.value = true
  }
  schedule(props.query)
})
watch(() => props.query, schedule)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <section
    class="rounded-lg border border-line p-3"
    :aria-label="t('projects.add.browserTitle')"
    :aria-busy="loading"
    data-testid="repository-browser"
  >
    <h3 class="mb-3 font-semibold">{{ t('projects.add.browserTitle') }}</h3>
    <p v-if="failed" role="alert" class="text-sm text-status-failed">
      {{ t('projects.add.browserFailed') }}
    </p>
    <p v-if="loading" class="text-sm text-muted">{{ t('projects.add.browserLoading') }}</p>
    <ul role="tree" class="max-h-64 overflow-y-auto" data-testid="folder-tree">
      <li v-for="root in visibleRoots" :key="root.path" role="treeitem">
        <button
          type="button"
          class="w-full break-all rounded px-2 py-1 text-left font-mono text-sm hover:bg-surface-raised"
          @click="choose(root.path)"
        >
          {{ root.path }}/
        </button>
        <ul
          v-if="listing && currentRoot?.path === root.path"
          role="group"
          class="ml-4 border-l border-line pl-2"
        >
          <li v-if="listing.path !== root.path" role="treeitem">
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                class="break-all rounded px-2 py-1 text-left font-mono text-sm hover:bg-surface-raised"
                data-testid="browser-path"
                @click="choose(listing.path!)"
              >
                {{ listing.path }}/
              </button>
              <button
                v-if="listing.parent"
                type="button"
                class="text-xs text-muted underline"
                @click="choose(listing.parent)"
              >
                {{ t('projects.add.browserUp') }}
              </button>
            </div>
          </li>
          <li v-for="folder in folders" :key="folder.path" role="treeitem" class="ml-3">
            <button
              type="button"
              class="w-full break-all rounded px-2 py-1 text-left font-mono text-sm hover:bg-surface-raised"
              @click="choose(folder.path)"
            >
              {{ folder.name }}/
            </button>
          </li>
          <li v-if="!folders.length && !loading" class="px-2 py-1 text-sm text-muted">
            {{ t('projects.add.browserEmpty') }}
          </li>
        </ul>
      </li>
      <li v-for="folder in matches" :key="folder.path" role="treeitem">
        <button
          type="button"
          class="w-full break-all rounded px-2 py-1 text-left font-mono text-sm hover:bg-surface-raised"
          @click="choose(folder.path)"
        >
          {{ folder.path }}/
        </button>
      </li>
    </ul>
    <p v-if="!loading && !visibleRoots.length && !matches.length" class="text-sm text-muted">
      {{ t('projects.add.browserEmpty') }}
    </p>
  </section>
</template>
