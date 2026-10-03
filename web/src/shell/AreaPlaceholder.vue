<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// Areas show this until their own issue fills them.
defineProps<{ titleKey: string; bodyKey: string }>()
const { t } = useI18n()
</script>

<template>
  <section class="mx-auto flex max-w-5xl flex-col gap-4 p-8">
    <h1 class="text-2xl font-semibold tracking-wide">{{ t(titleKey) }}</h1>
    <p class="glass rounded-xl border border-line p-6 text-muted">{{ t(bodyKey) }}</p>
  </section>
</template>
