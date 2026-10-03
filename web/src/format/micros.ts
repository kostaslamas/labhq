// Costs arrive as integer micro-USD (ADR 0002). Formatting stays in integer and string
// arithmetic: a float division would print 0.009699999 for some inputs and lose precision
// past 2^53 micros.
const MICROS_PER_USD = 1_000_000n
const FRACTION_DIGITS = 6
const MIN_FRACTION_DIGITS = 2

function toBigInt(micros: number | bigint): bigint {
  if (typeof micros === 'bigint') {
    return micros
  }
  if (!Number.isSafeInteger(micros)) {
    throw new RangeError(`micros must be a safe integer, got ${micros}`)
  }
  return BigInt(micros)
}

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

export function formatMicros(micros: number | bigint): string {
  const value = toBigInt(micros)
  const sign = value < 0n ? '-' : ''
  const magnitude = value < 0n ? -value : value
  const dollars = magnitude / MICROS_PER_USD
  const fraction = (magnitude % MICROS_PER_USD)
    .toString()
    .padStart(FRACTION_DIGITS, '0')
    .replace(/0+$/, '')
    .padEnd(MIN_FRACTION_DIGITS, '0')
  return `${sign}$${groupThousands(dollars.toString())}.${fraction}`
}
