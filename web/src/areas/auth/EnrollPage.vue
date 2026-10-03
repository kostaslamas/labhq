<script setup lang="ts">
import { Fingerprint } from 'lucide-vue-next'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { enrollPasskey } from '@/auth/ceremonies'
import { Button } from '@/ui'

import { useFailureMessage } from './useFailureMessage'

const { t } = useI18n()
const route = useRoute()
const describe = useFailureMessage()

// The link keeps its token after the `#`, which a browser never sends to any server.
const token = route.hash.slice(1)
const name = ref('')
const busy = ref(false)
const problem = ref<string | null>(null)
const done = ref(false)

async function enroll(): Promise<void> {
  busy.value = true
  problem.value = null
  try {
    await enrollPasskey(token, name.value.trim())
    done.value = true
  } catch (error) {
    problem.value = describe(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-5 px-4 py-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('auth.enroll.title') }}</h1>
    <div class="glass flex flex-col gap-4 rounded-xl border border-line p-6">
      <template v-if="done">
        <p data-testid="enrolled" role="status">{{ t('auth.enroll.done') }}</p>
        <Button as-child data-testid="go-sign-in">
          <RouterLink :to="{ name: 'login' }">{{ t('auth.enroll.sign_in') }}</RouterLink>
        </Button>
      </template>
      <p v-else-if="!token" data-testid="enroll-error" role="alert" class="text-status-failed">
        {{ t('auth.enroll.no_token') }}
      </p>
      <template v-else>
        <p class="text-muted">{{ t('auth.enroll.lead') }}</p>
        <label class="flex flex-col gap-1 text-sm">
          {{ t('auth.enroll.name_label') }}
          <input
            v-model="name"
            data-testid="passkey-name"
            maxlength="200"
            autocomplete="off"
            :placeholder="t('auth.enroll.name_placeholder')"
            class="h-9 rounded-md border border-line bg-transparent px-3"
          />
        </label>
        <Button data-testid="create-passkey" :disabled="busy" @click="enroll">
          <Fingerprint class="size-4" aria-hidden="true" />
          {{ busy ? t('auth.enroll.waiting') : t('auth.enroll.button') }}
        </Button>
        <p v-if="problem" role="alert" data-testid="enroll-error" class="text-status-failed">
          {{ problem }}
        </p>
      </template>
    </div>
  </section>
</template>
