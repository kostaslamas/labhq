import { useI18n } from 'vue-i18n'

/** Labels for registry keys the backend may extend; an unknown key shows as written. */
export function useLabels() {
  const i18n = useI18n()

  function known(prefix: string, key: string): string {
    const path = `${prefix}.${key}`
    return i18n.te(path) ? i18n.t(path) : key
  }

  return {
    typeLabel: (type: string) => known('approvals.types', type),
    confirmationLabel: (kind: string) => known('approvals.confirmation', kind),
  }
}
