<script setup lang="ts">
import { Bell, KeyRound, Languages } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { nextLocale, setLocale, type AppI18n } from '@/i18n'
import { navItems } from '@/router/areas'

import { useAppI18n } from './useAppI18n'

const { t, locale } = useI18n()
const i18n: AppI18n = useAppI18n()
const items = navItems(useRouter().options.routes)

function switchLanguage(): void {
  setLocale(i18n, nextLocale(locale.value))
}
</script>

<template>
  <aside
    class="glass sticky top-0 flex h-screen w-24 shrink-0 flex-col items-center gap-6 border-r border-line py-5"
  >
    <span class="text-sm font-bold tracking-[0.2em] text-accent" translate="no">labhq</span>
    <nav :aria-label="t('shell.nav_label')" class="flex w-full flex-1 flex-col gap-1 px-2">
      <RouterLink
        v-for="item in items"
        :key="item.path"
        :to="item.path"
        data-testid="nav-item"
        class="flex flex-col items-center gap-1 rounded-lg px-1 py-2.5 text-[0.7rem] text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
        active-class="bg-accent/20 text-foreground"
      >
        <component :is="item.icon" class="size-5" aria-hidden="true" />
        <span class="text-center leading-tight">{{ t(item.labelKey) }}</span>
      </RouterLink>
    </nav>
    <RouterLink
      :to="{ name: 'notifications' }"
      data-testid="notifications-link"
      class="flex flex-col items-center gap-1 rounded-lg px-1 py-2 text-[0.7rem] text-muted hover:bg-surface-raised hover:text-foreground"
    >
      <Bell class="size-4" aria-hidden="true" />
      {{ t('shell.notifications') }}
    </RouterLink>
    <RouterLink
      :to="{ name: 'passkeys' }"
      data-testid="passkeys-link"
      class="flex flex-col items-center gap-1 rounded-lg px-1 py-2 text-[0.7rem] text-muted hover:bg-surface-raised hover:text-foreground"
    >
      <KeyRound class="size-4" aria-hidden="true" />
      {{ t('shell.passkeys') }}
    </RouterLink>
    <button
      type="button"
      data-testid="switch-language"
      :aria-label="t('shell.switch_language_label')"
      class="flex flex-col items-center gap-1 rounded-lg px-1 py-2 text-[0.7rem] text-muted hover:bg-surface-raised hover:text-foreground"
      @click="switchLanguage"
    >
      <Languages class="size-4" aria-hidden="true" />
      {{ t('shell.switch_language') }}
    </button>
  </aside>
</template>
