<script setup lang="ts">
import CallCenterWidget from '@/areas/callcenter/CallCenterWidget.vue'

import AppSidebar from './AppSidebar.vue'
</script>

<template>
  <div class="flex min-h-screen">
    <AppSidebar />
    <main id="main" class="min-w-0 flex-1">
      <slot />
    </main>
    <CallCenterWidget />
  </div>
</template>
