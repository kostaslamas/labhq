<script setup lang="ts">
import { KeyRound } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import ApprovalDetail from '@/areas/approvals/ApprovalDetail.vue'
import { useFailureMessage } from '@/areas/auth/useFailureMessage'
import { useAuthStore } from '@/auth'
import { Button } from '@/ui'

import { useApproval } from './useApproval'

const { t } = useI18n()
const route = useRoute()
const auth = useAuthStore()
const describe = useFailureMessage()

const id = Number(route.params.id)
const { approval, status, load, settle } = useApproval(id)

const checking = ref(true)
const signingIn = ref(false)
const problem = ref<string | null>(null)

const needsSignIn = computed(() => !checking.value && !auth.signedIn)

onMounted(async () => {
  await auth.ensureLoaded()
  checking.value = false
  if (auth.signedIn) await load()
})

// The first prompt reveals the action; deciding asks again (step-up) in ApprovalActions.
async function signIn(): Promise<void> {
  signingIn.value = true
  problem.value = null
  try {
    await auth.signIn()
    await load()
  } catch (error) {
    problem.value = describe(error)
  } finally {
    signingIn.value = false
  }
}
</script>

<template>
  <section
    class="approve-page mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-4 px-4 py-6"
    data-testid="approve-page"
  >
    <h1 class="text-xl font-semibold tracking-wide">{{ t('approve.title') }}</h1>

    <p v-if="checking || status === 'loading'" class="text-muted" role="status">
      {{ t('approve.loading') }}
    </p>

    <div
      v-else-if="needsSignIn"
      class="glass flex flex-col gap-4 rounded-xl border border-line p-5"
      data-testid="approve-sign-in"
    >
      <p class="text-muted">{{ t('approve.sign_in_lead') }}</p>
      <Button data-testid="sign-in" :disabled="signingIn" @click="signIn">
        <KeyRound class="size-4" aria-hidden="true" />
        {{ signingIn ? t('auth.login.waiting') : t('auth.login.button') }}
      </Button>
      <p v-if="problem" role="alert" data-testid="login-error" class="text-status-failed">
        {{ problem }}
      </p>
      <p v-if="!auth.enrolled" class="text-sm text-muted" data-testid="not-enrolled">
        {{ t('approve.not_enrolled') }}
      </p>
    </div>

    <p v-else-if="status === 'unknown'" class="text-muted" data-testid="approve-unknown">
      {{ t('approve.unknown', { id }) }}
    </p>

    <div v-else-if="status === 'failed'" class="flex flex-col gap-3" data-testid="approve-failed">
      <p role="alert" class="text-status-failed">{{ t('approve.failed') }}</p>
      <Button variant="outline" @click="load">{{ t('approve.retry') }}</Button>
    </div>

    <ApprovalDetail v-else-if="approval" :approval="approval" @decided="settle" @stale="load" />
  </section>
</template>

<style scoped>
/* Phone ergonomics: every button reaches 44 px, and the two actions stack full width. */
.approve-page :deep(button) {
  min-height: 2.75rem;
}
.approve-page :deep([data-testid='approval-actions'] > div) {
  flex-direction: column;
}
.approve-page :deep([data-testid='approval-actions'] button) {
  width: 100%;
}
</style>
