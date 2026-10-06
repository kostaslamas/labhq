<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, type components } from '@/api'
import { Button } from '@/ui'

type Report = components['schemas']['CeoReportOut']

const props = defineProps<{ report: Report }>()
const emit = defineEmits<{ decided: [] }>()

const { t, locale } = useI18n()
const returning = ref(false)
const feedback = ref('')
const busy = ref(false)
const failed = ref(false)

function time(instant: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(instant),
  )
}

async function decide(decision: 'accept' | 'return'): Promise<void> {
  const taskId = props.report.task_id
  if (taskId === null || busy.value) return
  busy.value = true
  failed.value = false
  const options = {
    params: { path: { task_id: taskId } },
    body: { feedback: decision === 'return' ? feedback.value.trim() : '' },
  }
  try {
    const { data } =
      decision === 'accept'
        ? await api.POST('/api/org/tasks/{task_id}/accept', options)
        : await api.POST('/api/org/tasks/{task_id}/return', options)
    if (data) {
      returning.value = false
      feedback.value = ''
      emit('decided')
    } else {
      failed.value = true
    }
  } catch {
    failed.value = true
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <article
    class="glass mr-6 flex flex-col gap-3 rounded-xl border border-accent/40 p-4 sm:mr-16"
    data-testid="ceo-report"
  >
    <p class="text-xs text-muted">{{ t('ceo.report') }} · {{ time(report.created_at) }}</p>
    <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ report.text }}</p>
    <p v-if="report.refs.length" class="text-xs text-muted">{{ report.refs.join(', ') }}</p>
    <template v-if="report.awaiting_decision">
      <div v-if="!returning" class="flex flex-wrap gap-2">
        <Button :disabled="busy" data-testid="report-accept" @click="decide('accept')">
          {{ t('ceo.accept') }}
        </Button>
        <Button
          variant="outline"
          :disabled="busy"
          data-testid="report-return"
          @click="returning = true"
        >
          {{ t('ceo.return') }}
        </Button>
      </div>
      <form v-else class="flex flex-col gap-2" @submit.prevent="decide('return')">
        <label :for="`return-${report.id}`" class="text-sm font-medium">
          {{ t('ceo.returnWhy') }}
        </label>
        <textarea
          :id="`return-${report.id}`"
          v-model="feedback"
          rows="3"
          maxlength="4000"
          class="w-full rounded-xl border border-line bg-transparent p-3"
          data-testid="report-feedback"
        />
        <div class="flex flex-wrap gap-2">
          <Button type="submit" :disabled="busy || !feedback.trim()" data-testid="report-send-back">
            {{ t('ceo.sendBack') }}
          </Button>
          <Button type="button" variant="ghost" :disabled="busy" @click="returning = false">
            {{ t('ceo.cancel') }}
          </Button>
        </div>
      </form>
      <p v-if="failed" role="alert" class="text-sm text-status-failed">
        {{ t('ceo.decideFailed') }}
      </p>
    </template>
  </article>
</template>
