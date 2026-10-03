<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { layouts } from './shell/layouts'

const route = useRoute()
const layout = computed(() => layouts[route.meta.layout ?? 'shell'])
</script>

<template>
  <component :is="layout">
    <RouterView />
  </component>
</template>
