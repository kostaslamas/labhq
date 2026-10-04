<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, uiState, type components } from '@/api'
import { useLiveTopic } from '@/live'
import { StatusBadge } from '@/status'
import { Button, Mono } from '@/ui'

type Rule = components['schemas']['HealthRuleItem']

const { t, locale } = useI18n()

const rules = ref<Rule[]>([])
const loaded = ref(false)
const loadFailed = ref(false)
const failed = ref(false)

// An instant from the API is UTC; show it in the viewer's own zone and language.
function when(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}

async function load(): Promise<void> {
  const { data } = await api.GET('/api/health/rules')
  loadFailed.value = data === undefined
  if (data !== undefined) rules.value = data
  loaded.value = true
}

async function setEnabled(rule: Rule, enabled: boolean): Promise<void> {
  failed.value = false
  const { data } = await api.POST('/api/health/rules/{rule_id}/enabled', {
    params: { path: { rule_id: rule.id } },
    body: { enabled },
  })
  if (data === undefined) {
    failed.value = true
    return
  }
  rules.value = rules.value.map((current) => (current.id === data.id ? data : current))
}

onMounted(load)
// A new or resolved incident changes a rule's latest result.
useLiveTopic('incidents', load)
</script>

<template>
  <section class="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-8">
    <header class="flex flex-col gap-2">
      <h1 class="text-2xl font-semibold tracking-wide">{{ t('rules.title') }}</h1>
      <p class="text-muted">{{ t('rules.lead') }}</p>
    </header>

    <p v-if="loadFailed" role="alert" class="text-status-failed">{{ t('rules.load_failed') }}</p>
    <p v-if="failed" role="alert" class="text-status-failed" data-testid="rules-failed">
      {{ t('rules.failed') }}
    </p>
    <p v-if="!loaded" class="text-muted">{{ t('rules.loading') }}</p>
    <p v-else-if="rules.length === 0 && !loadFailed" class="text-muted">{{ t('rules.empty') }}</p>

    <ul class="flex flex-col gap-4" data-testid="rule-list">
      <li
        v-for="rule in rules"
        :key="rule.id"
        :data-testid="`rule-${rule.id}`"
        :data-enabled="rule.enabled"
        class="glass flex min-w-0 flex-col gap-3 rounded-xl border border-line p-4"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="flex min-w-0 flex-col gap-1">
            <h2 class="text-lg font-medium break-words">{{ rule.name }}</h2>
            <p class="flex flex-wrap items-center gap-x-2 text-sm text-muted">
              <Mono>{{ rule.type }}</Mono>
              <span>·</span>
              <span>{{ t(`rules.action.${rule.action}`) }}</span>
              <span>·</span>
              <span>
                {{ t('rules.host') }}:
                <Mono v-if="rule.host">{{ rule.host }}</Mono>
                <template v-else>{{ t('rules.all_hosts') }}</template>
              </span>
            </p>
          </div>
          <div class="flex items-center gap-3">
            <span
              v-if="!rule.enabled"
              class="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted"
              data-testid="rule-disabled"
            >
              {{ t('rules.disabled') }}
            </span>
            <Button
              variant="outline"
              size="sm"
              :data-testid="`toggle-${rule.id}`"
              @click="setEnabled(rule, !rule.enabled)"
            >
              {{ rule.enabled ? t('rules.disable') : t('rules.enable') }}
            </Button>
          </div>
        </div>

        <dl class="flex flex-col gap-2 text-sm">
          <div class="flex flex-col gap-0.5">
            <dt class="text-muted">{{ t('rules.why') }}</dt>
            <dd class="break-words" data-testid="rule-reason">{{ rule.reason }}</dd>
            <dd class="text-muted" data-testid="rule-creator">
              {{ t('rules.added_by') }} <Mono>{{ rule.created_by }}</Mono> ·
              {{ when(rule.created_at) }}
            </dd>
          </div>
          <div class="flex flex-col gap-0.5">
            <dt class="text-muted">{{ t('rules.settings') }}</dt>
            <dd>
              <Mono class="break-all">{{ JSON.stringify(rule.params) }}</Mono>
            </dd>
          </div>
          <div class="flex flex-col gap-0.5">
            <dt class="text-muted">{{ t('rules.latest') }}</dt>
            <dd v-if="rule.latest" class="flex flex-wrap items-center gap-2">
              <StatusBadge :state="uiState('incident_status', rule.latest.status)" />
              <span class="text-muted">
                {{
                  rule.latest.resolved_at
                    ? t('rules.resolved', { date: when(rule.latest.resolved_at) })
                    : t('rules.opened', { date: when(rule.latest.opened_at) })
                }}
              </span>
            </dd>
            <dd v-else class="text-muted">{{ t('rules.no_result') }}</dd>
          </div>
          <div v-if="!rule.enabled" class="text-muted">
            {{ t('rules.disabled_since', { date: when(rule.updated_at) }) }}
          </div>
        </dl>
      </li>
    </ul>
  </section>
</template>
