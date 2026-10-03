<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
</script>

<template>
  <div class="flex min-h-screen">
    <AppSidebar />
    <main id="main" class="min-w-0 flex-1">
      <slot />
    </main>
  </div>
</template>
