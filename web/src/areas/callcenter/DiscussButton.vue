<script setup lang="ts">
import { MessagesSquare } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import { Button } from '@/ui'

import { useCallCenter, type PinKind, type PinOption } from './store'

// Opens the widget with this proposal pinned. The pin travels as data, not as typed text.
const props = withDefaults(
  defineProps<{
    kind: PinKind
    id: number
    projectId?: number | null
    options?: PinOption[]
  }>(),
  { projectId: null, options: () => ['show'] },
)

const { t } = useI18n()
const callCenter = useCallCenter()

function discuss(): void {
  callCenter.discuss({
    kind: props.kind,
    id: props.id,
    projectId: props.projectId,
    options: props.options,
  })
}
</script>

<template>
  <Button variant="outline" size="sm" data-testid="discuss" @click="discuss">
    <MessagesSquare class="size-4" aria-hidden="true" />
    {{ t('callcenter.discuss') }}
  </Button>
</template>
