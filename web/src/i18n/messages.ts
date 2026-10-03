export const locales = ['el', 'en'] as const
export type Locale = (typeof locales)[number]

export interface MessageTree {
  [key: string]: string | MessageTree
}

export interface LocaleModule {
  default: MessageTree
}

const AREA_LOCALE_PATH = /\/areas\/([^/]+)\/locales\/([^/]+)\.json$/

export function isLocale(value: string): value is Locale {
  return (locales as readonly string[]).includes(value)
}

function emptyCatalog(): Record<Locale, MessageTree> {
  return Object.fromEntries(locales.map((locale) => [locale, {}])) as Record<Locale, MessageTree>
}

// Each area's messages live under its folder name, so two areas never collide.
export function collectAreaMessages(
  modules: Record<string, LocaleModule>,
): Record<Locale, MessageTree> {
  const catalog = emptyCatalog()
  for (const [path, module] of Object.entries(modules)) {
    const match = AREA_LOCALE_PATH.exec(path)
    const [, area, locale] = match ?? []
    if (!area || !locale || !isLocale(locale)) {
      throw new Error(`not an area locale file for ${locales.join('/')}: ${path}`)
    }
    catalog[locale][area] = module.default
  }
  return catalog
}

export function mergeCatalogs(
  shell: Record<Locale, MessageTree>,
  areas: Record<Locale, MessageTree>,
): Record<Locale, MessageTree> {
  const catalog = emptyCatalog()
  for (const locale of locales) {
    const clash = Object.keys(areas[locale]).find((name) => name in shell[locale])
    if (clash) {
      throw new Error(`area "${clash}" reuses a shell message namespace`)
    }
    catalog[locale] = { ...shell[locale], ...areas[locale] }
  }
  return catalog
}
