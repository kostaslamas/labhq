// An instant from the API is UTC; show it in the viewer's own zone and language.
export function formatInstant(
  locale: string,
  instant: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
): string {
  return new Intl.DateTimeFormat(locale, options).format(new Date(instant))
}

// The same agent always gets the same hue, so a speaker is recognisable down the chat.
export function avatarHue(agentId: number): number {
  return (agentId * 137) % 360
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => Array.from(word)[0] ?? '')
    .join('')
    .toUpperCase()
}
