<script setup lang="ts">
import { Keyboard, MessageCircle, Mic, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import ControlKeys from '@/areas/agentkeys/ControlKeys.vue'
import { Button } from '@/ui'

import ChatThread from './ChatThread.vue'
import PinnedBar from './PinnedBar.vue'
import RoomOffer from './RoomOffer.vue'
import RoomThread from './RoomThread.vue'
import { useCallCenter } from './store'
import { useChat } from './useChat'
import { useRooms } from './useRooms'
import VoiceHint from './VoiceHint.vue'

// The one chat of the app: a floating assistant at the bottom right of every page. Everything
// else is boards, cards and forms (issue #199).
const { t } = useI18n()
const callCenter = useCallCenter()
const chat = useChat()
const rooms = useRooms()

const voice = ref(false)
const keys = ref(false)
const PHONE = '(max-width: 639px)'

// What is waiting for the owner here: the CEO's offers of a room, reports to decide, answers
// they have not opened the widget for yet.
const seenTurns = ref(0)
const answered = computed(
  () => chat.turns.value.filter((turn) => turn.status === 'answered').length,
)
const badge = computed(
  () =>
    rooms.offered.value.length +
    chat.awaiting.value.length +
    (callCenter.open ? 0 : Math.max(0, answered.value - seenTurns.value)),
)
const panel = computed(() => (rooms.current.value && callCenter.panel === 'room' ? 'room' : 'chat'))

watch(
  () => callCenter.open,
  (open) => {
    if (open) seenTurns.value = answered.value
  },
)
watch(answered, (count) => {
  if (callCenter.open) seenTurns.value = count
})

// A started room is where the conversation goes on.
watch(
  () => rooms.current.value?.status,
  (status, before) => {
    if (status === 'running' && before === 'requested') callCenter.panel = 'room'
  },
)

function leavePage(): void {
  if (window.matchMedia(PHONE).matches) callCenter.close()
}
</script>

<template>
  <aside data-testid="callcenter" :aria-label="t('callcenter.title')">
    <section
      v-if="callCenter.open"
      role="dialog"
      :aria-label="t('callcenter.title')"
      class="glass fixed z-50 flex flex-col overflow-hidden border border-line shadow-2xl max-sm:inset-0 max-sm:rounded-none sm:right-4 sm:bottom-24 sm:h-[36rem] sm:max-h-[calc(100vh-7rem)] sm:w-[26rem] sm:rounded-2xl"
      data-testid="callcenter-panel"
    >
      <header class="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <div class="flex gap-1" role="tablist">
          <Button
            size="sm"
            :variant="panel === 'chat' ? 'default' : 'ghost'"
            role="tab"
            :aria-selected="panel === 'chat'"
            data-testid="tab-chat"
            @click="callCenter.panel = 'chat'"
          >
            {{ t('callcenter.title') }}
          </Button>
          <Button
            v-if="rooms.current.value"
            size="sm"
            :variant="panel === 'room' ? 'default' : 'ghost'"
            role="tab"
            :aria-selected="panel === 'room'"
            data-testid="tab-room"
            @click="callCenter.panel = 'room'"
          >
            {{ t('callcenter.room.tab') }}
          </Button>
        </div>
        <div class="flex gap-1">
          <Button
            v-if="chat.ceoId.value !== null && panel === 'chat'"
            size="icon"
            variant="ghost"
            :aria-label="t('callcenter.keys.button')"
            :aria-pressed="keys"
            data-testid="callcenter-keys"
            @click="keys = !keys"
          >
            <Keyboard class="size-4" aria-hidden="true" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            :aria-label="t('callcenter.voice.button')"
            :aria-pressed="voice"
            data-testid="callcenter-mic"
            @click="voice = !voice"
          >
            <Mic class="size-4" aria-hidden="true" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            :aria-label="t('callcenter.close')"
            data-testid="callcenter-close"
            @click="callCenter.close()"
          >
            <X class="size-4" aria-hidden="true" />
          </Button>
        </div>
      </header>

      <VoiceHint v-if="voice" />
      <div
        v-if="keys && panel === 'chat' && chat.ceoId.value !== null"
        class="border-b border-line px-4 py-3"
      >
        <ControlKeys :agent-id="chat.ceoId.value" />
      </div>
      <RoomOffer
        v-for="room in rooms.offered.value"
        :key="room.id"
        :room="room"
        :busy="rooms.busy.value"
        @start="rooms.start(room.id)"
        @decline="rooms.decline(room.id)"
      />
      <p
        v-if="rooms.failure.value && panel === 'chat'"
        role="alert"
        class="px-4 py-2 text-sm text-status-failed"
      >
        {{ rooms.failure.value }}
      </p>

      <template v-if="panel === 'room' && rooms.current.value">
        <RoomThread
          v-if="rooms.current.value.status !== 'requested'"
          :room="rooms.current.value"
          :detail="rooms.detail.value"
          :rooms="rooms"
        />
        <p v-else class="p-4 text-muted">{{ t('callcenter.room.notStarted') }}</p>
      </template>
      <template v-else>
        <PinnedBar v-if="callCenter.pin" :pin="callCenter.pin" @unpin="callCenter.unpin()" />
        <ChatThread :chat="chat" :pin="callCenter.pin" @navigated="leavePage" />
      </template>
    </section>

    <button
      type="button"
      class="fixed right-4 bottom-4 z-50 flex size-14 items-center justify-center rounded-full bg-accent text-accent-foreground shadow-lg hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      :class="callCenter.open ? 'max-sm:hidden' : ''"
      :aria-label="t(callCenter.open ? 'callcenter.close' : 'callcenter.open')"
      :aria-expanded="callCenter.open"
      data-testid="callcenter-launcher"
      @click="callCenter.toggle()"
    >
      <MessageCircle class="size-6" aria-hidden="true" />
      <span
        v-if="badge > 0"
        class="absolute -top-1 -right-1 flex min-w-5 items-center justify-center rounded-full bg-status-failed px-1 text-xs font-semibold text-white"
        data-testid="callcenter-badge"
        >{{ badge }}</span
      >
    </button>
  </aside>
</template>
