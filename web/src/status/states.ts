import { Ban, CircleCheck, CircleDashed, CircleX, Hand, LoaderCircle } from 'lucide-vue-next'
import type { Component } from 'vue'

// The one status vocabulary of the UI (plan §8.2.2). The API client maps backend values
// onto these keys; nothing else invents a status.
export const uiStates = ['done', 'working', 'waiting_on_you', 'blocked', 'failed', 'idle'] as const
export type UiState = (typeof uiStates)[number]

export interface StateStyle {
  labelKey: string
  // Literal class strings, so Tailwind sees every token it must generate.
  tone: string
  icon: Component
}

export const stateStyles: Record<UiState, StateStyle> = {
  done: {
    labelKey: 'status.done',
    tone: 'text-status-done bg-status-done/12 border-status-done/30',
    icon: CircleCheck,
  },
  working: {
    labelKey: 'status.working',
    tone: 'text-status-working bg-status-working/12 border-status-working/30',
    icon: LoaderCircle,
  },
  waiting_on_you: {
    labelKey: 'status.waiting_on_you',
    tone: 'text-status-waiting bg-status-waiting/12 border-status-waiting/30',
    icon: Hand,
  },
  blocked: {
    labelKey: 'status.blocked',
    tone: 'text-status-blocked bg-status-blocked/12 border-status-blocked/30',
    icon: Ban,
  },
  failed: {
    labelKey: 'status.failed',
    tone: 'text-status-failed bg-status-failed/12 border-status-failed/30',
    icon: CircleX,
  },
  idle: {
    labelKey: 'status.idle',
    tone: 'text-status-idle bg-status-idle/12 border-status-idle/30',
    icon: CircleDashed,
  },
}
