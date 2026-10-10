<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// Voice is the existing Call Center: an MCP connector in the owner's AI app, with its own
// voice mode. The web has no voice stack, so this says where to speak instead of adding one.
const { t } = useI18n()
</script>

<template>
  <div class="border-b border-line bg-surface-raised px-4 py-3 text-sm" data-testid="voice-hint">
    <p class="font-semibold">{{ t('callcenter.voice.title') }}</p>
    <p class="mt-1 text-muted">{{ t('callcenter.voice.body') }}</p>
  </div>
</template>
