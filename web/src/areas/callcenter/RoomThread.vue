<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, isErrorEnvelope } from '@/api'
import { formatMicros } from '@/format'
import { Button, Mono } from '@/ui'

import type { Room, RoomDetail, useRooms } from './useRooms'

// The owner, the CEO and the manager in one thread. The owner's words are recorded at once;
// each agent answers when its turn runs, so the thread fills in as the topic changes.
const props = defineProps<{
  room: Room
  detail: RoomDetail | null
  rooms: ReturnType<typeof useRooms>
}>()

const i18n = useI18n()
const { t, locale } = i18n
const draft = ref('')
const scroller = ref<HTMLElement | null>(null)
const interruptFailure = ref('')

function time(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { timeStyle: 'short' }).format(new Date(instant))
}

async function send(): Promise<void> {
  const text = draft.value.trim()
  if (!text) return
  draft.value = ''
  if (!(await props.rooms.say(props.room.id, text))) draft.value = text
}

// Esc interrupts a tmux manager that is mid-step, through the same control keys as an agent's
// page, so the owner's key press is recorded there too.
async function interrupt(agentId: number): Promise<void> {
  interruptFailure.value = ''
  try {
    const { error } = await api.POST('/api/agents/{agent_id}/keys', {
      params: { path: { agent_id: agentId } },
      body: { key: 'escape' },
    })
    if (error !== undefined) {
      interruptFailure.value = isErrorEnvelope(error)
        ? error.error.message
        : t('callcenter.room.interruptFailed')
    }
  } catch {
    interruptFailure.value = t('callcenter.room.interruptFailed')
  }
}

const TONE: Record<string, string> = {
  owner: 'ml-8 self-end border-line bg-accent/15',
  system: 'border-dashed border-line text-muted',
  agent: 'mr-8 border-line',
}

watch(
  () => props.detail?.messages.length,
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
  { immediate: true },
)
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col" data-testid="room-thread">
    <div class="flex items-center justify-between gap-2 border-b border-line px-4 py-2 text-xs">
      <span class="truncate text-muted">{{ room.project_name }} · {{ room.agenda }}</span>
      <span class="flex items-center gap-3">
        <Mono data-testid="room-turns">{{ room.turns_used }}/{{ room.turn_cap }}</Mono>
        <Mono
          :class="room.over_estimate ? 'text-status-failed' : ''"
          data-testid="room-cost"
          :title="t(`callcenter.room.cost.${room.equivalent_cost ? 'equivalent' : 'billed'}`)"
        >
          {{ formatMicros(room.cost_micros) }}
          <template v-if="room.cost_cap_micros !== null">
            / {{ formatMicros(room.cost_cap_micros) }}
          </template>
        </Mono>
        <span v-if="room.equivalent_cost" class="text-muted" data-testid="room-equivalent">
          {{ t('callcenter.room.cost.equivalent') }}
          <template v-if="room.plan_used_percent !== null">
            · {{ t('callcenter.room.cost.plan', { percent: Math.round(room.plan_used_percent) }) }}
          </template>
        </span>
      </span>
    </div>

    <div ref="scroller" class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <p v-if="!detail" class="text-muted">{{ t('callcenter.room.loading') }}</p>
      <div
        v-for="message in detail?.messages ?? []"
        :key="message.id"
        class="rounded-xl border p-3"
        :class="TONE[message.source]"
        :data-testid="`room-message-${message.source}`"
      >
        <p class="mb-1 text-xs text-muted">
          <span class="font-semibold text-foreground" data-testid="room-speaker">{{
            message.source === 'system' ? t('callcenter.room.system') : message.speaker
          }}</span>
          · {{ time(message.created_at) }}
        </p>
        <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ message.text }}</p>
      </div>

      <div
        v-if="room.waiting"
        class="flex flex-col gap-2 rounded-xl border border-status-waiting/50 p-3 text-sm"
        data-testid="room-waiting"
      >
        <p>
          {{ t('callcenter.room.waiting', { name: room.waiting.agent_name }) }}
          <span class="text-muted">· {{ room.waiting.reason }}</span>
        </p>
        <Button
          v-if="room.waiting.can_interrupt"
          size="sm"
          variant="outline"
          class="self-start"
          data-testid="room-interrupt"
          @click="interrupt(room.waiting.agent_id)"
        >
          {{ t('callcenter.room.interrupt', { name: room.waiting.agent_name }) }}
        </Button>
        <p v-if="interruptFailure" role="alert" class="text-status-failed">
          {{ interruptFailure }}
        </p>
      </div>

      <div
        v-if="detail && detail.decisions.length"
        class="rounded-xl border border-accent/40 p-3 text-sm"
        data-testid="room-decided"
      >
        <p>
          <span class="font-semibold">{{ t('callcenter.decided') }}</span>
          {{ detail.decisions.map((decision) => decision.text).join(' · ') }}
        </p>
        <p v-if="detail.action_items.length" class="mt-1 text-muted">
          {{ t('callcenter.room.confirmHint') }}
          <RouterLink :to="{ name: 'approvals' }" class="text-accent underline">{{
            t('callcenter.room.openApprovals')
          }}</RouterLink>
        </p>
      </div>
      <p v-else-if="room.status === 'ended' || room.status === 'failed'" class="text-muted">
        {{ t(`callcenter.room.over.${room.status}`) }}
      </p>
    </div>

    <form
      v-if="room.status === 'running'"
      class="flex flex-col gap-2 border-t border-line p-3"
      @submit.prevent="send"
    >
      <label for="room-message" class="sr-only">{{ t('callcenter.room.message') }}</label>
      <textarea
        id="room-message"
        v-model="draft"
        rows="2"
        maxlength="4000"
        :placeholder="t('callcenter.room.placeholder')"
        class="w-full resize-none rounded-xl border border-line bg-transparent p-3"
        data-testid="room-message"
        @keydown.enter.exact.prevent="send"
      />
      <p v-if="rooms.failure.value" role="alert" class="text-sm text-status-failed">
        {{ i18n.te(rooms.failure.value) ? t(rooms.failure.value) : rooms.failure.value }}
      </p>
      <div class="flex justify-between gap-2">
        <Button
          type="button"
          variant="outline"
          :disabled="rooms.busy.value"
          data-testid="room-close"
          @click="rooms.close(room.id)"
        >
          {{ t('callcenter.room.close') }}
        </Button>
        <Button type="submit" :disabled="!draft.trim()" data-testid="room-send">
          {{ t('callcenter.send') }}
        </Button>
      </div>
    </form>
  </div>
</template>
