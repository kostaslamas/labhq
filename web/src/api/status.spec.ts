import { describe, expect, it } from 'vitest'

import { uiStates } from '@/status'

import openapi from '../../openapi.json'
import {
  statusMap,
  uiState,
  type BackendStatus,
  type StatusMapping,
  type Vocabulary,
} from './status'

interface EnumSchema {
  enum?: string[]
}
interface ArraySchema {
  items: { $ref: string }
}

const schemas = openapi.components.schemas as Record<string, EnumSchema>
const vocabulary = openapi.components.schemas.Vocabulary.properties as Record<string, ArraySchema>

// The published enums, read from the committed schema: `{ run_status: ['queued', ...] }`.
const published = Object.fromEntries(
  Object.entries(vocabulary).map(([kind, field]) => {
    const name = field.items.$ref.split('/').at(-1) ?? ''
    return [kind, schemas[name]?.enum ?? []]
  }),
)

describe('backend status vocabulary', () => {
  it('maps every published value of every enum onto a UI state', () => {
    expect(Object.keys(statusMap).sort()).toEqual(Object.keys(published).sort())
    for (const [kind, values] of Object.entries(published)) {
      expect(values.length, kind).toBeGreaterThan(0)
      const states = statusMap[kind as keyof Vocabulary] as Record<string, string>
      expect(Object.keys(states).sort(), kind).toEqual([...values].sort())
      for (const value of values) {
        expect(uiStates, `${kind}.${value}`).toContain(states[value])
      }
    }
  })

  it('looks a value up by kind', () => {
    expect(uiState('run_status', 'interrupted')).toBe('idle')
    expect(uiState('approval_status', 'pending')).toBe('waiting_on_you')
    expect(uiState('incident_status', 'open')).toBe('failed')
  })
})

// Type-level guards, checked by `vue-tsc` (npm run typecheck): an unused
// `@ts-expect-error` is itself an error, so each line below proves a rejection.
type GrownValue = Omit<Vocabulary, 'run_status'> & {
  run_status: (BackendStatus<'run_status'> | 'paused_by_owner')[]
}
type GrownEnum = Vocabulary & { meeting_status: ('scheduled' | 'held')[] }

// Spread into a literal so the check is structural, as it is for `statusMap` itself;
// comparing two `StatusMapping` instances would only compare their type arguments.
// @ts-expect-error a new value of an existing enum without a UI state
export const missingValue: StatusMapping<GrownValue> = { ...statusMap }
// @ts-expect-error a new backend enum without a mapping
export const missingEnum: StatusMapping<GrownEnum> = { ...statusMap }
export const unchanged: StatusMapping<Vocabulary> = { ...statusMap }
export const notAState: StatusMapping<Pick<Vocabulary, 'call_status'>> = {
  // @ts-expect-error a value mapped onto something that is not a UI state
  call_status: { open: 'working', closed: 'finished' },
}
