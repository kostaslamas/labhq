import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { createAppI18n } from '@/i18n'

import StatusBadge from './StatusBadge.vue'
import { stateStyles, uiStates } from './states'

describe('status vocabulary', () => {
  it('has the six UI states, each with a label, a colour and an icon', () => {
    expect(uiStates).toEqual(['done', 'working', 'waiting_on_you', 'blocked', 'failed', 'idle'])
    for (const state of uiStates) {
      const style = stateStyles[state]
      expect(style.labelKey).toBe(`status.${state}`)
      expect(style.tone).toMatch(/text-status-/)
      expect(style.icon).toBeTruthy()
    }
  })

  it.each([
    ['en', 'Waiting on you'],
    ['el', 'Περιμένει εσένα'],
  ] as const)('renders the badge label in %s', (locale, label) => {
    const wrapper = mount(StatusBadge, {
      props: { state: 'waiting_on_you' },
      global: { plugins: [createAppI18n({ locale })] },
    })
    expect(wrapper.text()).toBe(label)
    expect(wrapper.attributes('data-state')).toBe('waiting_on_you')
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
