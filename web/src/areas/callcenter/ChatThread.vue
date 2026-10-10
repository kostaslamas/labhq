<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { Button } from '@/ui'

import ChatActions from './ChatActions.vue'
import type { Pin } from './store'
import type { useChat } from './useChat'

// The one place the owner types to the CEO (issue #199). Context travels as data.
const props = defineProps<{ chat: ReturnType<typeof useChat>; pin: Pin | null }>()
const emit = defineEmits<{ navigated: [] }>()

const { t, locale } = useI18n()
const route = useRoute()
const draft = ref('')
const scroller = ref<HTMLElement | null>(null)

function time(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { timeStyle: 'short' }).format(new Date(instant))
}

async function send(): Promise<void> {
  if (await props.chat.send(draft.value, props.pin, route.path)) {
    draft.value = ''
  }
}

watch(
  () => props.chat.turns.value.map((turn) => `${turn.id}:${turn.status}`).join(),
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
  { immediate: true },
)
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col" data-testid="chat-thread">
    <div ref="scroller" class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <p v-if="chat.loadFailed.value" role="alert" class="text-status-failed">
        {{ t('callcenter.errors.loadFailed') }}
      </p>
      <p v-else-if="chat.configured.value === false" class="text-muted">
        {{ t('callcenter.setup') }}
        <RouterLink :to="{ name: 'projects' }" class="text-accent underline">{{
          t('callcenter.setupLink')
        }}</RouterLink>
      </p>
      <p v-else-if="chat.turns.value.length === 0" class="text-muted">
        {{ t('callcenter.empty') }}
      </p>
      <template v-for="turn in chat.turns.value" :key="turn.id">
        <div
          class="ml-8 self-end rounded-xl border border-line bg-accent/15 p-3"
          data-testid="chat-owner"
        >
          <p class="mb-1 text-xs text-muted">
            {{ t('callcenter.you') }} · {{ time(turn.created_at) }}
            <template v-if="turn.context?.pinned">
              ·
              {{ t(`callcenter.pin.${turn.context.pinned.kind}`, { id: turn.context.pinned.id }) }}
            </template>
          </p>
          <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ turn.text }}</p>
        </div>
        <div class="mr-8 rounded-xl border border-line p-3" data-testid="chat-ceo">
          <p class="mb-1 text-xs text-muted">{{ t('callcenter.ceo') }}</p>
          <template v-if="turn.reply">
            <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ turn.reply }}</p>
            <ChatActions
              v-if="turn.actions?.length"
              :actions="turn.actions ?? []"
              @navigated="emit('navigated')"
            />
          </template>
          <p
            v-else
            class="text-sm"
            :class="turn.status === 'failed' ? 'text-status-failed' : 'text-muted'"
          >
            {{ t(`callcenter.status.${turn.status}`) }}
          </p>
        </div>
      </template>
    </div>

    <form
      v-if="chat.configured.value"
      class="flex flex-col gap-2 border-t border-line p-3"
      @submit.prevent="send"
    >
      <label for="callcenter-message" class="sr-only">{{ t('callcenter.message') }}</label>
      <textarea
        id="callcenter-message"
        v-model="draft"
        rows="3"
        maxlength="4000"
        :placeholder="t('callcenter.placeholder')"
        class="w-full resize-none rounded-xl border border-line bg-transparent p-3"
        data-testid="callcenter-message"
        @keydown.enter.exact.prevent="send"
      />
      <p v-if="chat.failure.value" role="alert" class="text-sm text-status-failed">
        {{ t(chat.failure.value) }}
      </p>
      <Button
        type="submit"
        class="self-end"
        :disabled="chat.sending.value || chat.waiting.value || !draft.trim()"
        data-testid="callcenter-send"
      >
        {{ chat.sending.value ? t('callcenter.sending') : t('callcenter.send') }}
      </Button>
    </form>
  </div>
</template>
