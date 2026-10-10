import { computed, ref } from 'vue'

import { api, isErrorEnvelope, type components } from '@/api'
import { useLiveTopic } from '@/live'

import type { Pin } from './store'

export type Turn = components['schemas']['CeoChatTurn']
export type Report = components['schemas']['CeoReportOut']

// Refusals the CEO endpoint names, each mapped to one sentence in `callcenter.errors`.
const FAILURE_BY_CODE: Partial<Record<string, string>> = {
  ceo_budget_stop: 'callcenter.errors.budgetStop',
  ceo_inactive: 'callcenter.errors.inactive',
  ceo_busy: 'callcenter.errors.busy',
  proposal_not_found: 'callcenter.errors.proposalGone',
}

// The conversation with the CEO. Live topics keep it fresh; there is no polling loop.
export function useChat() {
  const turns = ref<Turn[]>([])
  const reports = ref<Report[]>([])
  const configured = ref<boolean | null>(null)
  const ceoId = ref<number | null>(null)
  const loadFailed = ref(false)
  const sending = ref(false)
  const failure = ref('')

  const waiting = computed(() => turns.value.some((t) => ['queued', 'running'].includes(t.status)))
  const awaiting = computed(() => reports.value.filter((report) => report.awaiting_decision))

  async function load(): Promise<void> {
    try {
      const [assignment, messages, reported] = await Promise.all([
        api.GET('/api/org/ceo'),
        api.GET('/api/org/ceo/messages'),
        api.GET('/api/org/ceo/reports'),
      ])
      if (!assignment.data || !Array.isArray(messages.data) || !Array.isArray(reported.data)) {
        loadFailed.value = true
        return
      }
      configured.value = assignment.data.id !== null
      ceoId.value = assignment.data.id
      turns.value = messages.data
      reports.value = reported.data
      loadFailed.value = false
    } catch {
      loadFailed.value = true
    }
  }

  async function send(text: string, pin: Pin | null, route: string): Promise<boolean> {
    const words = text.trim()
    if (!words || sending.value || waiting.value || !configured.value) return false
    sending.value = true
    failure.value = ''
    try {
      const { data, error } = await api.POST('/api/org/ceo/messages', {
        body: {
          text: words,
          context: {
            route,
            project_id: pin?.projectId ?? null,
            pinned: pin ? { kind: pin.kind, id: pin.id, options: pin.options } : null,
          },
        },
      })
      if (data) {
        turns.value = [...turns.value, data]
        return true
      }
      const code = isErrorEnvelope(error) ? error.error.code : ''
      failure.value = FAILURE_BY_CODE[code] ?? 'callcenter.errors.sendFailed'
      await load()
      return false
    } catch {
      failure.value = 'callcenter.errors.sendFailed'
      return false
    } finally {
      sending.value = false
    }
  }

  void load()
  useLiveTopic('runs', load)
  useLiveTopic('tasks', load)

  return {
    turns,
    reports,
    configured,
    ceoId,
    loadFailed,
    sending,
    failure,
    waiting,
    awaiting,
    load,
    send,
  }
}
