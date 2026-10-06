<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { uiState, type components } from '@/api'
import ControlKeys from '@/areas/agentkeys/ControlKeys.vue'
import { StatusBadge } from '@/status'
import { Button, cn, Mono } from '@/ui'

import BudgetMeter from './BudgetMeter.vue'

type Member = components['schemas']['TeamMember']

const props = defineProps<{ member: Member; open: ReadonlySet<number> }>()
const emit = defineEmits<{ toggle: [id: number]; edit: [id: number] }>()
const { t } = useI18n()

const expandable = computed(() => props.member.reports.length > 0)
const expanded = computed(() => expandable.value && props.open.has(props.member.id))
const label = computed(() =>
  t(expanded.value ? 'projects.team.collapse' : 'projects.team.expand', {
    name: props.member.title,
  }),
)
</script>

<template>
  <li :data-agent="member.id" :aria-expanded="expandable ? expanded : undefined" role="treeitem">
    <div class="flex min-w-0 items-start gap-2 py-2">
      <button
        v-if="expandable"
        type="button"
        class="mt-0.5 shrink-0 rounded p-0.5 text-muted hover:text-foreground focus-visible:outline-2"
        :aria-label="label"
        :aria-expanded="expanded"
        data-testid="team-toggle"
        @click="emit('toggle', member.id)"
      >
        <ChevronRight :class="cn('size-4 transition-transform', expanded && 'rotate-90')" />
      </button>
      <span v-else class="size-5 shrink-0" aria-hidden="true" />

      <div class="grid min-w-0 flex-1 gap-x-4 gap-y-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
        <div class="flex min-w-0 flex-col gap-0.5">
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span class="break-words font-medium" data-testid="team-title">{{ member.title }}</span>
            <StatusBadge :state="uiState('agent_status', member.status)" />
          </div>
          <p class="flex flex-wrap gap-x-2 text-xs text-muted">
            <Mono>{{ member.role }}</Mono>
            <span aria-hidden="true">·</span>
            <Mono>{{ member.adapter }}</Mono>
          </p>
          <Button
            v-if="member.status !== 'retired'"
            type="button"
            variant="ghost"
            size="sm"
            class="self-start"
            data-testid="edit-agent"
            @click="emit('edit', member.id)"
          >
            {{ t('projects.agent.edit') }}
          </Button>
          <!-- Only a tmux agent has a pane to send a key to; the SDK ones are never asked. -->
          <ControlKeys
            v-if="member.adapter === 'tmux' && member.status !== 'retired'"
            :agent-id="member.id"
          />
        </div>
        <BudgetMeter :budget="member.budget" />
      </div>
    </div>

    <ul v-if="expanded" role="group" class="ml-3 border-l border-line pl-3">
      <TeamNode
        v-for="report in member.reports"
        :key="report.id"
        :member="report"
        :open="open"
        @toggle="emit('toggle', $event)"
        @edit="emit('edit', $event)"
      />
    </ul>
  </li>
</template>
