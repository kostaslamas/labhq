<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, isErrorEnvelope } from '@/api'
import { Button } from '@/ui'

// How long the pane gets to redraw before it is read again: a mode change is not instant.
const REDRAW_MS = 800

const props = defineProps<{ agentId: number }>()
const i18n = useI18n()
const t = i18n.t.bind(i18n)

const keys = ref<string[]>([])
const sending = ref(false)
const failure = ref('')
const screen = ref('')
let redraw: ReturnType<typeof setTimeout> | undefined

function label(key: string): string {
  return i18n.te(`agentkeys.key.${key}`) ? t(`agentkeys.key.${key}`) : key
}

async function load(): Promise<void> {
  const { data } = await api.GET('/api/agents/{agent_id}/keys', {
    params: { path: { agent_id: props.agentId } },
  })
  keys.value = data?.live ? data.keys : []
}

async function refreshScreen(): Promise<void> {
  const { data } = await api.GET('/api/agents/{agent_id}/screen', {
    params: { path: { agent_id: props.agentId } },
  })
  if (data?.screen) screen.value = data.screen
}

async function send(key: string): Promise<void> {
  if (sending.value) return
  sending.value = true
  failure.value = ''
  try {
    const { data, error } = await api.POST('/api/agents/{agent_id}/keys', {
      params: { path: { agent_id: props.agentId } },
      body: { key },
    })
    if (data) {
      screen.value = data.screen
      clearTimeout(redraw)
      redraw = setTimeout(() => void refreshScreen(), REDRAW_MS)
    } else {
      failure.value = isErrorEnvelope(error) ? error.error.message : t('agentkeys.failed')
    }
  } catch {
    failure.value = t('agentkeys.failed')
  } finally {
    sending.value = false
  }
}

onMounted(() => void load())
onUnmounted(() => clearTimeout(redraw))
watch(() => props.agentId, load)
</script>

<template>
  <div v-if="keys.length > 0" class="flex flex-col gap-2" data-testid="control-keys">
    <div class="flex flex-wrap gap-2" role="group" :aria-label="t('agentkeys.group')">
      <Button
        v-for="key in keys"
        :key="key"
        type="button"
        variant="ghost"
        size="sm"
        :disabled="sending"
        :data-testid="`control-key-${key}`"
        @click="send(key)"
      >
        {{ label(key) }}
      </Button>
    </div>
    <p v-if="failure" role="alert" class="text-sm text-status-failed" data-testid="control-failure">
      {{ failure }}
    </p>
    <pre
      v-if="screen"
      class="max-h-64 overflow-auto rounded-xl border border-line p-3 font-mono text-xs"
      :aria-label="t('agentkeys.screen')"
      data-testid="control-screen"
      >{{ screen }}</pre>
  </div>
</template>
