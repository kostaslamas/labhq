<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { components } from '@/api'
import { Button } from '@/ui'

import TeamNode from './TeamNode.vue'

type Member = components['schemas']['TeamMember']

const props = defineProps<{ team: Member[] }>()
const { t } = useI18n()

// Ids of the expanded nodes. The roots start open, so the first two levels are visible.
const open = reactive(new Set<number>())
let seeded = false

function everyParent(members: Member[]): number[] {
  return members.flatMap((m) => (m.reports.length ? [m.id, ...everyParent(m.reports)] : []))
}

function toggle(id: number): void {
  if (!open.delete(id)) open.add(id)
}

// A live refetch replaces the tree; the owner's open nodes stay open.
watch(
  () => props.team,
  (team) => {
    if (seeded) return
    seeded = team.length > 0
    for (const root of team) open.add(root.id)
  },
  { immediate: true },
)

function expandAll(): void {
  for (const id of everyParent(props.team)) open.add(id)
}

function collapseAll(): void {
  open.clear()
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <p v-if="team.length === 0" class="text-sm text-muted">{{ t('projects.team.empty') }}</p>
    <template v-else>
      <div class="flex gap-2">
        <Button variant="ghost" size="sm" data-testid="expand-all" @click="expandAll">
          {{ t('projects.team.expandAll') }}
        </Button>
        <Button variant="ghost" size="sm" data-testid="collapse-all" @click="collapseAll">
          {{ t('projects.team.collapseAll') }}
        </Button>
      </div>
      <ul role="tree" class="divide-y divide-line" data-testid="team-tree">
        <TeamNode
          v-for="root in team"
          :key="root.id"
          :member="root"
          :open="open"
          @toggle="toggle"
        />
      </ul>
    </template>
  </div>
</template>
