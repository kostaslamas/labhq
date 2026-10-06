import type { UiState } from '@/status'

import type { components } from './schema'

// Every backend status enum, as `GET /api/vocabulary` publishes it in the OpenAPI schema.
export type Vocabulary = components['schemas']['Vocabulary']
export type StatusKind = keyof Vocabulary
type ValueOf<List> = List extends readonly (infer Value extends string)[] ? Value : never
export type BackendStatus<Kind extends StatusKind> = ValueOf<Vocabulary[Kind]>

// One UI state for every value of every enum. A new enum or a new value on the backend
// regenerates `schema.d.ts`, and this type then rejects `statusMap` until it is mapped.
export type StatusMapping<Source> = {
  readonly [Kind in keyof Source]: Readonly<Record<ValueOf<Source[Kind]>, UiState>>
}

export const statusMap: StatusMapping<Vocabulary> = {
  agent_status: {
    pending_approval: 'waiting_on_you',
    active: 'working',
    paused: 'idle',
    retired: 'done',
  },
  approval_status: {
    pending: 'waiting_on_you',
    // Approved and not yet executed: the engine is carrying it out.
    approved: 'working',
    rejected: 'done',
    executed: 'done',
    execution_failed: 'failed',
    cancelled: 'idle',
  },
  call_request_status: {
    pending: 'waiting_on_you',
    answered: 'done',
    failed: 'failed',
    expired: 'idle',
  },
  call_status: {
    open: 'working',
    closed: 'done',
  },
  host_status: {
    unknown: 'idle',
    up: 'done',
    degraded: 'blocked',
    down: 'failed',
  },
  incident_status: {
    open: 'failed',
    resolved: 'done',
  },
  meeting_status: {
    // Requested meetings wait for the owner's start_meeting approval.
    requested: 'waiting_on_you',
    running: 'working',
    ended: 'done',
    failed: 'failed',
    cancelled: 'idle',
  },
  notification_status: {
    pending: 'working',
    sent: 'done',
    failed: 'failed',
  },
  project_status: {
    active: 'working',
    paused: 'idle',
    archived: 'done',
  },
  proposal_status: {
    // A Call Center wording waits for the owner's yes before the CEO gets it.
    pending: 'waiting_on_you',
    sent: 'done',
    rejected: 'idle',
  },
  question_status: {
    pending: 'waiting_on_you',
    answered: 'done',
  },
  run_status: {
    queued: 'idle',
    running: 'working',
    succeeded: 'done',
    failed: 'failed',
    // An interrupt is the owner's choice, not a failure (spikes/agent_sdk/RESULTS.md).
    interrupted: 'idle',
    timed_out: 'failed',
  },
  task_status: {
    backlog: 'idle',
    todo: 'idle',
    in_progress: 'working',
    in_review: 'waiting_on_you',
    blocked: 'blocked',
    done: 'done',
    cancelled: 'idle',
  },
  wakeup_status: {
    pending: 'idle',
    dispatched: 'working',
    refused: 'blocked',
    cancelled: 'idle',
  },
}

export function uiState<Kind extends StatusKind>(kind: Kind, value: BackendStatus<Kind>): UiState {
  const states: Readonly<Record<BackendStatus<Kind>, UiState>> = statusMap[kind]
  return states[value]
}
