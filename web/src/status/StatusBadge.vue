<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { cn } from '@/ui/utils'

import { stateStyles, type UiState } from './states'

const props = defineProps<{ state: UiState }>()
const { t } = useI18n()
const style = computed(() => stateStyles[props.state])
</script>

<template>
  <span
    :data-state="state"
    :class="
      cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        style.tone,
      )
    "
  >
    <component :is="style.icon" class="size-3.5" aria-hidden="true" />
    {{ t(style.labelKey) }}
  </span>
</template>
