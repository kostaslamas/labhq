<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { BellOff, BellRing } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

import { authClient } from '@/auth/client'
import { usePush } from '@/push/usePush'
import { Button } from '@/ui'

const { t } = useI18n()
const { availability, subscribed, busy, failure, enable, disable } = usePush()

// Whether Web Push is the notifier in use; the step still works when it is not, but the owner
// should know approvals will go elsewhere.
const active = ref(true)

onMounted(async () => {
  const { data } = await authClient().GET('/api/push/status')
  active.value = data?.active ?? true
})
</script>

<template>
  <section class="mx-auto flex max-w-xl flex-col gap-5 p-4 sm:p-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t('notifications.title') }}</h1>
    <p class="text-muted">{{ t('notifications.lead') }}</p>

    <div class="glass flex flex-col gap-4 rounded-xl border border-line p-6">
      <div
        v-if="availability === 'needs_install'"
        data-testid="needs-install"
        class="flex flex-col gap-2"
      >
        <h2 class="text-lg font-medium">{{ t('notifications.needs_install.title') }}</h2>
        <p class="text-muted">{{ t('notifications.needs_install.body') }}</p>
      </div>
      <p v-else-if="availability === 'unsupported'" data-testid="unsupported" class="text-muted">
        {{ t('notifications.unsupported') }}
      </p>
      <p v-else-if="availability === 'denied'" data-testid="denied" class="text-muted">
        {{ t('notifications.denied') }}
      </p>
      <template v-else>
        <p data-testid="push-state" role="status">
          {{ subscribed ? t('notifications.enabled') : t('notifications.disabled') }}
        </p>
        <Button
          v-if="!subscribed"
          class="self-start"
          data-testid="enable-notifications"
          :disabled="busy"
          @click="enable"
        >
          <BellRing class="size-4" aria-hidden="true" />
          {{ busy ? t('notifications.working') : t('notifications.enable') }}
        </Button>
        <Button
          v-else
          variant="outline"
          class="self-start"
          data-testid="disable-notifications"
          :disabled="busy"
          @click="disable"
        >
          <BellOff class="size-4" aria-hidden="true" />
          {{ t('notifications.disable') }}
        </Button>
      </template>
      <p v-if="failure" role="alert" data-testid="push-error" class="text-status-failed">
        {{ t(`notifications.errors.${failure}`) }}
      </p>
      <p v-if="!active" data-testid="push-inactive" class="text-sm text-muted">
        {{ t('notifications.inactive') }}
      </p>
    </div>
  </section>
</template>
