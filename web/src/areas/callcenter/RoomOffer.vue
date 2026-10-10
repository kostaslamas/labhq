<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { formatMicros } from '@/format'
import { Button } from '@/ui'

import type { Room } from './useRooms'

// The CEO proposed a decision room. The owner sees what it may cost and decides here; this
// is the room's `start_meeting` approval, a tap.
defineProps<{ room: Room; busy: boolean }>()
defineEmits<{ start: []; decline: [] }>()

const { t } = useI18n()
</script>

<template>
  <article
    class="flex flex-col gap-2 border-b border-line bg-status-waiting/10 px-4 py-3 text-sm"
    data-testid="room-offer"
  >
    <p>{{ t('callcenter.offer.title', { project: room.project_name }) }}</p>
    <p class="text-muted">{{ room.agenda }}</p>
    <p v-if="room.estimate_micros !== null" data-testid="room-estimate">
      {{ t('callcenter.offer.estimate', { cost: formatMicros(room.estimate_micros) }) }}
    </p>
    <div class="flex flex-wrap gap-2">
      <Button size="sm" :disabled="busy" data-testid="room-start" @click="$emit('start')">
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
