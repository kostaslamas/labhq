import { createI18n } from 'vue-i18n'

import el from './locales/el.json'
import en from './locales/en.json'
import {
  collectAreaMessages,
  isLocale,
  locales,
  mergeCatalogs,
  type Locale,
  type LocaleModule,
} from './messages'

export { locales, type Locale } from './messages'

// A new area adds locales/{el,en}.json in its folder; nothing here changes.
export const discoveredAreaMessages = import.meta.glob<LocaleModule>('../areas/*/locales/*.json', {
  eager: true,
})

const STORAGE_KEY = 'labhq.locale'

function storedLocale(): Locale | undefined {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value && isLocale(value) ? value : undefined
  } catch {
    return undefined
  }
}

function browserLocale(): Locale {
  const preferred = navigator.languages.map((tag) => tag.slice(0, 2).toLowerCase())
  return preferred.find(isLocale) ?? 'en'
}

export interface AppI18nOptions {
  areaMessages?: Record<string, LocaleModule>
  locale?: Locale
}

export function createAppI18n(options: AppI18nOptions = {}) {
  const messages = mergeCatalogs(
    { el, en },
    collectAreaMessages(options.areaMessages ?? discoveredAreaMessages),
  )
  const locale = options.locale ?? storedLocale() ?? browserLocale()
  document.documentElement.lang = locale
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages,
    missingWarn: import.meta.env.DEV,
    fallbackWarn: import.meta.env.DEV,
  })
}

export type AppI18n = ReturnType<typeof createAppI18n>

export function setLocale(i18n: AppI18n, locale: Locale): void {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // Private windows may refuse storage; the choice then lasts for this page only.
  }
}

export function nextLocale(current: string): Locale {
  const index = locales.findIndex((locale) => locale === current)
  return locales[(index + 1) % locales.length] ?? 'en'
}
