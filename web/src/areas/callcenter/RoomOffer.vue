<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatMicros } from '@/format'
import { Button } from '@/ui'

import type { Room } from './useRooms'

// The CEO proposed a decision room. The owner sees what it may cost and decides here; this
// is the room's `start_meeting` approval, a tap.
const props = defineProps<{ room: Room; busy: boolean }>()
defineEmits<{ start: []; decline: [] }>()

const { t } = useI18n()

// A room starts only when the owner can see both its range and its hard cap.
const shown = computed(
  () =>
    props.room.estimate_micros !== null &&
    props.room.estimate_high_micros !== null &&
    props.room.cost_cap_micros !== null,
)
const kind = computed(() => (props.room.equivalent_cost ? 'equivalent' : 'billed'))
</script>

<template>
  <article
    class="flex flex-col gap-2 border-b border-line bg-status-waiting/10 px-4 py-3 text-sm"
    data-testid="room-offer"
  >
    <p>{{ t('callcenter.offer.title', { project: room.project_name }) }}</p>
    <p class="text-muted">{{ room.agenda }}</p>
    <template v-if="shown">
      <p data-testid="room-estimate">
        {{
          t(`callcenter.offer.estimate.${kind}`, {
            low: formatMicros(room.estimate_micros ?? 0),
            high: formatMicros(room.estimate_high_micros ?? 0),
          })
        }}
      </p>
      <p class="text-muted" data-testid="room-estimate-source">
        {{ t(`callcenter.offer.source.${room.estimate_source ?? 'fallback'}`) }}
      </p>
      <p data-testid="room-cap">
        {{ t('callcenter.offer.cap', { cap: formatMicros(room.cost_cap_micros ?? 0) }) }}
      </p>
    </template>
    <div class="flex flex-wrap gap-2">
      <Button size="sm" :disabled="busy || !shown" data-testid="room-start" @click="$emit('start')">
        {{ t('callcenter.offer.start') }}
      </Button>
      <Button
        size="sm"
        variant="outline"
        :disabled="busy"
        data-testid="room-decline"
        @click="$emit('decline')"
      >
        {{ t('callcenter.offer.decline') }}
      </Button>
    </div>
  </article>
</template>
