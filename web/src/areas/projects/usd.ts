const MICROS_DIGITS = 6
const USD_PATTERN = /^(\d{1,12})(?:\.(\d{1,6}))?$/

/**
 * A USD amount typed by a person as integer micro-USD (ADR 0002), by digits and never by
 * float. Empty means no budget (`null`); anything that is not a plain amount is `undefined`.
 */
export function usdToMicros(text: string): number | null | undefined {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const match = USD_PATTERN.exec(trimmed)
  if (!match) return undefined
  const [, whole = '0', fraction = ''] = match
  return Number(whole + fraction.padEnd(MICROS_DIGITS, '0'))
}
