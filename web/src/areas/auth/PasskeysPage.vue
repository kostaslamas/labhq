<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import type { components } from '@/api'
import { authClient } from '@/auth/client'
import { useAuthStore } from '@/auth'
import { Button, Mono } from '@/ui'

type Credential = components['schemas']['Credential']
type Link = components['schemas']['EnrollmentLink']

const { t, locale } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const credentials = ref<Credential[]>([])
const link = ref<Link | null>(null)
const failed = ref(false)

// An instant from the API is UTC; show it in the viewer's own zone and language.
function when(instant: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(locale.value, options).format(new Date(instant))
}

async function load(): Promise<void> {
  const { data } = await authClient().GET('/api/auth/credentials')
  credentials.value = data ?? []
}

async function revoke(id: number): Promise<void> {
  failed.value = false
  const { error } = await authClient().DELETE('/api/auth/credentials/{credential_id}', {
    params: { path: { credential_id: id } },
  })
  failed.value = error !== undefined
  await load()
}

async function addAnother(): Promise<void> {
  failed.value = false
  const { data } = await authClient().POST('/api/auth/enrollment-links', {
    body: { target: 'public' },
  })
  link.value = data ?? null
  failed.value = data === undefined
}

async function signOut(): Promise<void> {
  await auth.signOut()
  await router.replace({ name: 'login' })
}

onMounted(load)
</script>

<template>
  <section class="mx-auto flex max-w-3xl flex-col gap-6 p-4 sm:p-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('auth.passkeys.title') }}</h1>
    <p v-if="failed" role="alert" class="text-status-failed">{{ t('auth.passkeys.failed') }}</p>

    <ul class="glass divide-y divide-line rounded-xl border border-line" data-testid="passkey-list">
      <li
        v-for="credential in credentials"
        :key="credential.id"
        class="flex flex-wrap items-center justify-between gap-3 p-4"
      >
        <div class="flex flex-col">
          <span class="font-medium">{{ credential.name }}</span>
          <span class="text-sm text-muted">
            <Mono>{{ credential.rp_id }}</Mono>
            ·
            {{
              credential.revoked
                ? t('auth.passkeys.revoked')
                : t('auth.passkeys.created', {
                    date: when(credential.created_at, { dateStyle: 'medium' }),
                  })
            }}
          </span>
        </div>
        <Button
          v-if="!credential.revoked"
          variant="outline"
          size="sm"
          :data-testid="`revoke-${credential.id}`"
          @click="revoke(credential.id)"
        >
          {{ t('auth.passkeys.revoke') }}
        </Button>
      </li>
    </ul>

    <div class="glass flex flex-col gap-4 rounded-xl border border-line p-6">
      <h2 class="text-lg font-medium">{{ t('auth.passkeys.add_title') }}</h2>
      <p class="text-muted">{{ t('auth.passkeys.add_lead') }}</p>
      <Button class="self-start" data-testid="add-passkey" @click="addAnother">
        {{ t('auth.passkeys.add_button') }}
      </Button>
      <div v-if="link" class="flex flex-col gap-3" data-testid="enrollment-link">
        <img :src="link.qr" :alt="t('auth.passkeys.qr_alt')" class="size-48 rounded bg-white p-2" />
        <Mono class="break-all text-xs">{{ link.url }}</Mono>
        <p class="text-sm text-muted">
          {{ t('auth.passkeys.expires', { time: when(link.expires_at, { timeStyle: 'short' }) }) }}
        </p>
      </div>
    </div>

    <Button variant="ghost" class="self-start" data-testid="sign-out" @click="signOut">
      {{ t('auth.passkeys.sign_out') }}
    </Button>
  </section>
</template>
