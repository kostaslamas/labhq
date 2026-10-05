import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { components } from '@/api'
import { createAppI18n } from '@/i18n'

import BudgetMeter from './BudgetMeter.vue'
import TeamTree from './TeamTree.vue'
import meterSource from './BudgetMeter.vue?raw'

type Budget = components['schemas']['Budget']
type Member = components['schemas']['TeamMember']

const plugins = [createAppI18n({ locale: 'en' })]

function budget(spent: number, limit: number | null, state: Budget['state']): Budget {
  return {
    spent_micros: spent,
    budget_micros: limit,
    state,
    used_percent: limit ? Math.trunc((spent * 100) / limit) : null,
  }
}

function member(id: number, reports: Member[] = []): Member {
  return {
    id,
    role: 'worker',
    title: `Agent ${id}`,
    adapter: 'fake',
    kind: 'fake',
    reports_to: null,
    adopted: false,
    status: 'active',
    budget: budget(0, null, 'allow'),
    reports,
  }
}

describe('BudgetMeter', () => {
  it('renders amounts from integer micros in mono, with no float formatting', () => {
    const wrapper = mount(BudgetMeter, {
      props: { budget: budget(9_700, 1_000_000, 'allow') },
      global: { plugins },
    })
    expect(wrapper.get('[data-testid="budget-spent"]').text()).toBe('$0.0097')
    expect(wrapper.get('[data-testid="budget-limit"]').text()).toBe('$1.00')
    for (const id of ['budget-spent', 'budget-limit', 'budget-percent']) {
      expect(wrapper.get(`[data-testid="${id}"]`).attributes()).toHaveProperty('data-mono')
    }
    const code = meterSource.replace(/\/\/.*$/gm, '')
    expect(code).not.toMatch(/toFixed|toPrecision|parseFloat|Intl\.NumberFormat/)
    expect(code).not.toMatch(/\s\/\s/)
  })

  it.each([
    ['allow', false],
    ['warn', true],
    ['stop', true],
  ] as const)('shows a warning for the %s verdict only when it is not allow', (state, shown) => {
    const wrapper = mount(BudgetMeter, {
      props: { budget: budget(800_000, 1_000_000, state) },
      global: { plugins },
    })
    expect(wrapper.find('[data-testid="budget-warning"]').exists()).toBe(shown)
    expect(wrapper.attributes('data-budget-state')).toBe(state)
  })

  it('caps the bar at the full width past the limit', () => {
    const wrapper = mount(BudgetMeter, {
      props: { budget: budget(1_500_000, 1_000_000, 'stop') },
      global: { plugins },
    })
    expect(wrapper.get('[role="progressbar"] > div').attributes('style')).toContain('width: 100%')
  })

  it('says there is no limit instead of a bar', () => {
    const wrapper = mount(BudgetMeter, {
      props: { budget: budget(5, null, 'allow') },
      global: { plugins },
    })
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('no limit')
  })
})

describe('TeamTree', () => {
  const chain = [member(1, [member(2, [member(3, [member(4)])])])]

  it('opens the roots and expands to the full depth one node at a time', async () => {
    const wrapper = mount(TeamTree, { props: { team: chain }, global: { plugins } })
    const titles = () => wrapper.findAll('[data-testid="team-title"]').map((n) => n.text())
    expect(titles()).toEqual(['Agent 1', 'Agent 2'])

    await wrapper.get('[data-agent="2"] [data-testid="team-toggle"]').trigger('click')
    expect(titles()).toEqual(['Agent 1', 'Agent 2', 'Agent 3'])
    await wrapper.get('[data-agent="3"] [data-testid="team-toggle"]').trigger('click')
    expect(titles()).toEqual(['Agent 1', 'Agent 2', 'Agent 3', 'Agent 4'])

    await wrapper.get('[data-agent="1"] [data-testid="team-toggle"]').trigger('click')
    expect(titles()).toEqual(['Agent 1'])
  })

  it('expands and collapses everything at once', async () => {
    const wrapper = mount(TeamTree, { props: { team: chain }, global: { plugins } })
    await wrapper.get('[data-testid="expand-all"]').trigger('click')
    expect(wrapper.findAll('[data-testid="team-title"]')).toHaveLength(4)
    await wrapper.get('[data-testid="collapse-all"]').trigger('click')
    expect(wrapper.findAll('[data-testid="team-title"]')).toHaveLength(1)
  })

  it('keeps the owner’s open nodes when the tree is refetched', async () => {
    const wrapper = mount(TeamTree, { props: { team: chain }, global: { plugins } })
    await wrapper.get('[data-testid="expand-all"]').trigger('click')
    await wrapper.setProps({ team: structuredClone(chain) })
    expect(wrapper.findAll('[data-testid="team-title"]')).toHaveLength(4)
  })
})
