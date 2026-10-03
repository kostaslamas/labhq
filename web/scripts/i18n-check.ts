// `npm run i18n:check`: every key exists in every locale, and every key the source names
// exists in some locale. Runs on plain Node (type stripping), so it imports nothing from src.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

export const LOCALES = ['el', 'en'] as const

interface MessageTree {
  [key: string]: string | MessageTree
}

interface LocaleGroup {
  namespace: string
  dir: string
}

export interface I18nReport {
  errors: string[]
  keys: number
  sourceFiles: number
}

// `t('a.b')`, `$t("a.b")`, `te('a.b')` and props named `*Key` / `*-key`, the convention for
// passing a key on (`labelKey: 'today.nav'`, `title-key="today.nav"`). Dynamic keys are not
// matched; they must come from a literal the scanner can see, such as a `labelKey` entry.
const KEY_USES = [
  /(?<![\w.])\$?te?\(\s*['"`]([\w.-]+)['"`]/g,
  /(?:[a-z]Key|-key|keypath)\s*[:=]\s*['"]([\w.-]+)['"]/g,
]
const SOURCE_SUFFIXES = ['.ts', '.vue']
const SKIPPED = new Set(['__fixtures__', 'node_modules'])

function flatten(tree: MessageTree, prefix: string): string[] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'string' ? [path] : flatten(value, path)
  })
}

function isDirectory(path: string): boolean {
  try {
    return statSync(path).isDirectory()
  } catch {
    return false
  }
}

function localeGroups(src: string): LocaleGroup[] {
  const shell = { namespace: '', dir: join(src, 'i18n', 'locales') }
  const areasDir = join(src, 'areas')
  const areas = isDirectory(areasDir)
    ? readdirSync(areasDir)
        .filter((name) => isDirectory(join(areasDir, name, 'locales')))
        .sort()
        .map((name) => ({ namespace: name, dir: join(areasDir, name, 'locales') }))
    : []
  return [shell, ...areas]
}

function readKeys(file: string, namespace: string): string[] | undefined {
  try {
    return flatten(JSON.parse(readFileSync(file, 'utf8')) as MessageTree, namespace)
  } catch {
    return undefined
  }
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) {
      return SKIPPED.has(entry.name) ? [] : sourceFiles(path)
    }
    const isSource = SOURCE_SUFFIXES.some((suffix) => entry.name.endsWith(suffix))
    return isSource && !entry.name.endsWith('.spec.ts') ? [path] : []
  })
}

function usedKeys(text: string): { key: string; line: number }[] {
  return KEY_USES.flatMap((pattern) =>
    [...text.matchAll(pattern)].map((match) => ({
      key: match[1] ?? '',
      line: text.slice(0, match.index).split('\n').length,
    })),
  )
}

export function checkI18n(webRoot: string): I18nReport {
  const src = join(webRoot, 'src')
  const errors: string[] = []
  const defined = new Set<string>()

  for (const group of localeGroups(src)) {
    const keysByLocale = new Map<string, Set<string>>()
    for (const locale of LOCALES) {
      const file = join(group.dir, `${locale}.json`)
      const keys = readKeys(file, group.namespace)
      if (!keys) {
        errors.push(`${relative(webRoot, file)}: missing or not valid JSON`)
      }
      keysByLocale.set(locale, new Set(keys))
      keys?.forEach((key) => defined.add(key))
    }
    const union = new Set([...keysByLocale.values()].flatMap((keys) => [...keys]))
    for (const key of [...union].sort()) {
      const missing = LOCALES.filter((locale) => !keysByLocale.get(locale)?.has(key))
      if (missing.length) {
        errors.push(`${key}: defined in some locales but missing in ${missing.join(', ')}`)
      }
    }
  }

  const files = isDirectory(src) ? sourceFiles(src) : []
  for (const file of files) {
    for (const use of usedKeys(readFileSync(file, 'utf8'))) {
      if (!defined.has(use.key)) {
        errors.push(
          `${relative(webRoot, file)}:${use.line}: uses "${use.key}", which no locale defines`,
        )
      }
    }
  }
  // A check that saw nothing must not pass (CONTRIBUTING.md §6).
  if (!defined.size) errors.push('no message keys found')
  if (!files.length) errors.push('no source files found')
  return { errors, keys: defined.size, sourceFiles: files.length }
}

function main(): number {
  const webRoot = fileURLToPath(new URL('..', import.meta.url))
  const report = checkI18n(webRoot)
  report.errors.forEach((error) => console.error(`error: ${error}`))
  console.log(
    `i18n: ${report.keys} keys in ${LOCALES.join(', ')}, ${report.sourceFiles} source files, ${report.errors.length} errors`,
  )
  return report.errors.length ? 1 : 0
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main()
}
