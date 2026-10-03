import { inject, type InjectionKey } from 'vue'

import type { AppI18n } from '@/i18n'

export const appI18nKey: InjectionKey<AppI18n> = Symbol('appI18n')

// The sidebar needs the i18n instance itself, not only the composer, to persist the choice.
export function useAppI18n(): AppI18n {
  const i18n = inject(appI18nKey)
  if (!i18n) {
    throw new Error('the app i18n instance was not provided')
  }
  return i18n
}
