<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { uiState } from '@/api'
import { StatusBadge } from '@/status'
import { Mono } from '@/ui'

import ApprovalDetail from './ApprovalDetail.vue'
import type { Approval } from './decide'
import { useApprovals } from './useApprovals'
import { useLabels } from './useLabels'

const { t } = useI18n()
const { typeLabel } = useLabels()
const { items, loading, failed, refresh } = useApprovals()

const chosen = ref<number | null>(null)
// The first approval until the owner picks one; the list is pending first.
const selected = computed(
  () => items.value.find((item) => item.id === chosen.value) ?? items.value[0] ?? null,
)
const pending = computed(() => items.value.filter((item) => item.status === 'pending').length)

async function onDecided(approval: Approval): Promise<void> {
  const at = items.value.findIndex((item) => item.id === approval.id)
  if (at >= 0) items.value.splice(at, 1, approval)
  await refresh()
}
</script>

<template>
  <section class="mx-auto flex max-w-6xl flex-col gap-6 p-4 sm:p-8">
    <header class="flex flex-wrap items-baseline justify-between gap-2">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('approvals.title') }}</h1>
      <p v-if="pending > 0" class="text-sm text-muted" data-testid="pending-count">
        {{ t('approvals.pending_count', { count: pending }) }}
      </p>
    </header>

    <p v-if="failed" role="alert" class="text-status-failed">{{ t('approvals.load_failed') }}</p>
    <p v-else-if="!loading && items.length === 0" class="text-muted" data-testid="approvals-empty">
      {{ t('approvals.empty') }}
    </p>

    <div v-if="items.length > 0" class="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
      <ul
        class="glass divide-y divide-line self-start rounded-xl border border-line"
        :aria-label="t('approvals.list_label')"
        data-testid="approval-list"
      >
        <li v-for="item in items" :key="item.id">
          <button
            type="button"
            class="flex w-full flex-col gap-1 p-4 text-left hover:bg-surface-raised"
            :aria-current="selected?.id === item.id ? 'true' : undefined"
            :data-testid="`approval-${item.id}`"
            @click="chosen = item.id"
          >
            <span class="flex flex-wrap items-center justify-between gap-2">
              <span class="font-medium">{{ typeLabel(item.type) }}</span>
              <StatusBadge :state="uiState('approval_status', item.status)" />
            </span>
            <span class="text-xs text-muted">
              <Mono>A{{ item.id }}</Mono>
              ·
              {{ t(`approvals.risk.${item.risk_class}`) }}
              <template v-if="item.project"> · {{ item.project.name }}</template>
            </span>
          </button>
        </li>
      </ul>

      <ApprovalDetail
        v-if="selected"
        :key="selected.id"
        :approval="selected"
        @decided="onDecided"
        @stale="refresh"
      />
      <p v-else class="text-muted">{{ t('approvals.empty_detail') }}</p>
    </div>
  </section>
</template>
