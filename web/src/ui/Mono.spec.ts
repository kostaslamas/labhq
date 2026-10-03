import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { formatMicros } from '@/format'

import Mono from './Mono.vue'

describe('Mono', () => {
  it('renders machine values in the mono font', () => {
    const wrapper = mount(Mono, { slots: { default: formatMicros(9700) } })
    expect(wrapper.classes()).toContain('font-mono')
    expect(wrapper.text()).toBe('$0.0097')
  })
})
