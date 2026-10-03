<script setup lang="ts">
// Machine values (ids, branches, costs) always render in mono (plan §8.2.4).
withDefaults(defineProps<{ as?: string }>(), { as: 'span' })
</script>

<template>
  <component :is="as" class="font-mono tabular-nums" data-mono>
    <slot />
  </component>
</template>
