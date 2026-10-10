<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { PinKind } from './store'
import { useDecisions } from './useDecisions'

// "Decided: …" under the card the decision room was about. Its action items still wait for
// the owner's approval, so they are listed as pending until then.
const props = defineProps<{ kind: PinKind; id: number }>()

const { t } = useI18n()
const decisions = useDecisions()
const decided = computed(() => decisions.about(props.kind, props.id))
</script>

<template>
  <div v-if="decided.length" class="flex flex-col gap-2 text-sm" data-testid="decided">
    <div v-for="room in decided" :key="room.meeting_id" class="flex flex-col gap-1">
      <p>
        <span class="font-semibold">{{ t('callcenter.decided') }}</span>
        {{ room.decisions.join(' · ') }}
      </p>
      <ul v-if="room.actions.length" class="list-disc pl-5 text-muted">
        <li v-for="(action, index) in room.actions" :key="index">
          {{ action.text }}
          <template v-if="action.approval_status === 'pending'">
            ·
            <RouterLink :to="{ name: 'approvals' }" class="text-accent underline">{{
              t('callcenter.awaitsYou')
            }}</RouterLink>
          </template>
        </li>
      </ul>
    </div>
  </div>
</template>
