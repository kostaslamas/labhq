<script setup lang="ts">
import { KeyRound } from 'lucide-vue-next'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { safeNext, useAuthStore } from '@/auth'
import { Button, Mono } from '@/ui'

import { useFailureMessage } from './useFailureMessage'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const describe = useFailureMessage()

const busy = ref(false)
const problem = ref<string | null>(null)

async function signIn(): Promise<void> {
  busy.value = true
  problem.value = null
  try {
    await auth.signIn()
    await router.replace(safeNext(route.query.next) ?? '/')
  } catch (error) {
    problem.value = describe(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-5 px-4 py-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('auth.login.title') }}</h1>
    <div class="glass flex flex-col gap-4 rounded-xl border border-line p-6">
      <p class="text-muted">{{ t('auth.login.lead') }}</p>
      <Button data-testid="sign-in" :disabled="busy" @click="signIn">
        <KeyRound class="size-4" aria-hidden="true" />
        {{ busy ? t('auth.login.waiting') : t('auth.login.button') }}
      </Button>
      <p v-if="problem" role="alert" data-testid="login-error" class="text-status-failed">
        {{ problem }}
      </p>
      <div v-if="!auth.enrolled" data-testid="not-enrolled" class="flex flex-col gap-2 text-sm">
        <p class="text-muted">{{ t('auth.login.not_enrolled') }}</p>
        <Mono>labhq passkey enroll</Mono>
      </div>
    </div>
  </section>
</template>
