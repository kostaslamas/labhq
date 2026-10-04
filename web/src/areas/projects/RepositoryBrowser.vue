<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'
import { Button } from '@/ui'

type Listing = components['schemas']['BrowserListing']

const emit = defineEmits<{ selected: [path: string]; close: [] }>()
const { t } = useI18n()
const listing = ref<Listing | null>(null)
const loading = ref(false)
const failed = ref(false)

async function load(path?: string): Promise<void> {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    const { data } = await api.GET('/api/repository-browser', { params: { query: { path } } })
    if (data) listing.value = data
    else failed.value = true
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <section
    class="rounded-lg border border-line p-3"
    :aria-label="t('projects.add.browserTitle')"
    :aria-busy="loading"
    data-testid="repository-browser"
  >
    <div class="mb-3 flex items-center justify-between gap-3">
      <h3 class="font-semibold">{{ t('projects.add.browserTitle') }}</h3>
      <Button type="button" variant="outline" @click="emit('close')">
        {{ t('projects.add.browserClose') }}
      </Button>
    </div>
    <p v-if="failed" role="alert" class="text-sm text-status-failed">
      {{ t('projects.add.browserFailed') }}
    </p>
    <p v-if="loading" class="text-sm text-muted">{{ t('projects.add.browserLoading') }}</p>
    <template v-if="listing">
      <div class="mb-3 flex flex-wrap gap-2">
        <button
          v-for="root in listing.roots"
          :key="root.path"
          type="button"
          class="rounded border border-line px-2 py-1 text-sm hover:bg-surface-raised"
          :disabled="loading"
          @click="load(root.path)"
        >
          {{ root.path }}
        </button>
      </div>
      <template v-if="listing.path">
        <p class="mb-2 break-all font-mono text-xs text-muted" data-testid="browser-path">
          {{ listing.path }}
        </p>
        <div class="mb-3 flex flex-wrap gap-2">
          <Button
            v-if="listing.parent"
            type="button"
            variant="outline"
            :disabled="loading"
            @click="load(listing.parent)"
          >
            {{ t('projects.add.browserUp') }}
          </Button>
          <Button
            type="button"
            :disabled="loading"
            data-testid="browser-select"
            @click="emit('selected', listing.path)"
          >
            {{ t('projects.add.browserSelect') }}
          </Button>
        </div>
        <ul
          v-if="listing.folders.length"
          class="max-h-64 overflow-y-auto rounded border border-line"
        >
          <li v-for="folder in listing.folders" :key="folder.path">
            <button
              type="button"
              class="w-full px-3 py-2 text-left hover:bg-surface-raised disabled:opacity-50"
              :disabled="loading"
              @click="load(folder.path)"
            >
              {{ folder.name }}/
            </button>
          </li>
        </ul>
        <p v-else class="text-sm text-muted">{{ t('projects.add.browserEmpty') }}</p>
      </template>
    </template>
  </section>
</template>
