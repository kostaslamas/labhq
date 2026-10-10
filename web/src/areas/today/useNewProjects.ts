import { onMounted, ref } from 'vue'

import { api, type components } from '@/api'

export type NewProject = components['schemas']['NewProject']

/** Projects the automatic scan announced that the owner has not yet added or skipped. */
export function useNewProjects() {
  const projects = ref<NewProject[]>([])

  async function load(): Promise<void> {
    try {
      const { data } = await api.GET('/api/inventory/new-projects')
      projects.value = Array.isArray(data) ? data : []
    } catch {
      // Nothing to announce is the quiet answer; the next visit asks again.
    }
  }

  onMounted(load)
  return { projects }
}
