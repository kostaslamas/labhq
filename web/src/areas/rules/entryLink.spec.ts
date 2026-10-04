import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { components } from '@/api'
import { createAppI18n } from '@/i18n'

import ProjectCard from '../projects/ProjectCard.vue'

type Card = components['schemas']['ProjectCard']

function card(name: string): Card {
  return {
    id: 1,
    name,
    status: 'active',
    budget: { spent_micros: 0, budget_micros: null, state: 'allow', used_percent: null },
    open_tasks: [],
    latest_deliverable: null,
  }
}

function render(name: string) {
  return mount(ProjectCard, {
    props: { card: card(name) },
    global: {
      plugins: [createAppI18n({ locale: 'en' })],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('entry to the health rules', () => {
  it('is offered on the infra project card only', () => {
    expect(render('infra').find('[data-testid="rules-link"]').text()).toBe('Health rules')
    expect(render('website').find('[data-testid="rules-link"]').exists()).toBe(false)
  })
})
