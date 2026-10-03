// `npm run dist:check`: the built bundle references no external host. Fonts and styles
// ship inside web/dist (plan §8.3), so the UI makes no request outside its own origin.
import { readdirSync, readFileSync } from 'node:fs'
import { extname, join, relative } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

export interface DistReport {
  errors: string[]
  files: number
}

const ABSOLUTE = String.raw`(?:https?:)?\/\/[^\s"'()<>]+`

// Only references a browser would fetch: attributes in HTML, url() and @import in CSS,
// module imports in JS. A URL inside a string or comment is not a request.
const FETCHES: Record<string, RegExp[]> = {
  '.html': [new RegExp(String.raw`\b(?:src|href|srcset|content)\s*=\s*["'](${ABSOLUTE})`, 'g')],
  '.css': [
    new RegExp(String.raw`url\(\s*["']?(${ABSOLUTE})`, 'g'),
    new RegExp(String.raw`@import\s+["'](${ABSOLUTE})`, 'g'),
  ],
  '.js': [
    new RegExp(String.raw`\bimport\s*\(\s*["'](${ABSOLUTE})`, 'g'),
    new RegExp(String.raw`\bfrom\s*["'](${ABSOLUTE})`, 'g'),
  ],
}
const FONT_SUFFIXES = new Set(['.woff2', '.woff'])

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    return entry.isDirectory() ? filesUnder(path) : [path]
  })
}

export function checkDist(distDir: string): DistReport {
  let files: string[]
  try {
    files = filesUnder(distDir)
  } catch {
    return { errors: [`${distDir}: no build output; run npm run build first`], files: 0 }
  }
  const errors: string[] = []
  for (const file of files) {
    const patterns = FETCHES[extname(file)] ?? []
    const text = patterns.length ? readFileSync(file, 'utf8') : ''
    for (const match of patterns.flatMap((pattern) => [...text.matchAll(pattern)])) {
      errors.push(`${relative(distDir, file)}: references external ${match[1]}`)
    }
  }
  if (!files.some((file) => file.endsWith('index.html'))) {
    errors.push('index.html is missing from the build')
  }
  if (!files.some((file) => FONT_SUFFIXES.has(extname(file)))) {
    errors.push('no font files in the build: fonts must be bundled, not linked')
  }
  return { errors, files: files.length }
}

function main(): number {
  const distDir = fileURLToPath(new URL('../dist', import.meta.url))
  const report = checkDist(distDir)
  report.errors.forEach((error) => console.error(`error: ${error}`))
  console.log(`dist: ${report.files} files checked, ${report.errors.length} external references`)
  return report.errors.length ? 1 : 0
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main()
}
