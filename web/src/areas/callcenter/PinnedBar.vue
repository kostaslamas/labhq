<script setup lang="ts">
import { Pin as PinIcon, X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import type { Pin } from './store'

defineProps<{ pin: Pin }>()
defineEmits<{ unpin: [] }>()

const { t } = useI18n()
</script>

<template>
  <div
    class="flex items-center justify-between gap-2 border-b border-line bg-accent/10 px-4 py-2 text-sm"
    data-testid="callcenter-pin"
  >
    <span class="flex min-w-0 items-center gap-2">
      <PinIcon class="size-4 shrink-0 text-accent" aria-hidden="true" />
      <span class="truncate">{{ t(`callcenter.pin.${pin.kind}`, { id: pin.id }) }}</span>
    </span>
    <button
      type="button"
      class="rounded p-1 text-muted hover:bg-surface-raised hover:text-foreground"
      :aria-label="t('callcenter.pin.clear')"
      data-testid="callcenter-unpin"
      @click="$emit('unpin')"
    >
      <X class="size-4" aria-hidden="true" />
    </button>
  </div>
</template>
