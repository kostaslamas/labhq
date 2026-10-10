import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

import { describe, expect, it } from 'vitest'

// The Call Center widget is the only place the owner types to the CEO (issue #199). This
// reads the whole web app and fails when another page grows a free-text input, a `/ceo` route
// or a call that sends the CEO or a decision room a message. A new input must be listed here
// with where its text goes, so someone has read it.
const SRC = join(import.meta.dirname, '..', '..')
const WIDGET = `areas${sep}callcenter${sep}`

// Text entry that does not reach the CEO, by file, with where the text goes.
const NOT_THE_CEO: Record<string, string> = {
  [`areas${sep}ceo${sep}ReportCard.vue`]: 'feedback returning a task to its manager',
  [`areas${sep}projects${sep}AddAgentForm.vue`]: 'a new agent: title and settings',
  [`areas${sep}projects${sep}EditAgentForm.vue`]: 'an agent: title and budget',
  [`areas${sep}projects${sep}AddProjectForm.vue`]: 'a new project: name and folder',
  [`areas${sep}auth${sep}EnrollPage.vue`]: 'the name of a passkey',
  [`areas${sep}meetings${sep}MeetingPage.vue`]:
    'joining a standup, planning or review; the API refuses a decision room (room_in_call_center)',
  [`areas${sep}channels${sep}ChannelsPage.vue`]: 'chat channel setup fields',
  [`areas${sep}sessions${sep}SessionScanPage.vue`]: 'a folder path for the session scan',
}

const NON_TEXT_INPUT = /type=["'](checkbox|radio|hidden|submit|button|file|range|color)["']/
const TEXT_ENTRY = /<textarea\b|contenteditable|<input\b[^>]*>/g

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return entry.name === '__fixtures__' ? [] : sources(path)
    return /\.(vue|ts)$/.test(entry.name) && !entry.name.endsWith('.spec.ts') ? [path] : []
  })
}

const files = sources(SRC).map((path) => ({
  name: relative(SRC, path),
  text: readFileSync(path, 'utf-8'),
}))

function hasTextEntry(text: string): boolean {
  return (text.match(TEXT_ENTRY) ?? []).some((tag) => !NON_TEXT_INPUT.test(tag))
}

describe('free text to the CEO', () => {
  it('reads the app, not nothing', () => {
    expect(files.length).toBeGreaterThan(50)
    const widget = files.filter((file) => file.name.startsWith(WIDGET) && hasTextEntry(file.text))
    expect(widget.map((file) => file.name).sort()).toEqual([
      `${WIDGET}ChatThread.vue`,
      `${WIDGET}RoomThread.vue`,
    ])
  })

  it('has no text input outside the widget that is not listed as going elsewhere', () => {
    const found = files
      .filter((file) => !file.name.startsWith(WIDGET) && hasTextEntry(file.text))
      .map((file) => file.name)
      .sort()
    expect(found.filter((name) => !(name in NOT_THE_CEO))).toEqual([])
  })

  it('lists no file that has stopped having a text input', () => {
    const found = new Set(files.filter((file) => hasTextEntry(file.text)).map((file) => file.name))
    expect(Object.keys(NOT_THE_CEO).filter((name) => !found.has(name))).toEqual([])
  })

  it('sends the CEO or a room a message from the widget alone', () => {
    const senders = ['/api/org/ceo/messages', '/api/callcenter/rooms/{room_id}/messages']
    const outside = files
      .filter((file) => !file.name.startsWith(WIDGET))
      .filter((file) => !file.name.startsWith(`api${sep}`))
      .filter((file) => senders.some((path) => file.text.includes(path)))
    expect(outside.map((file) => file.name)).toEqual([])
  })

  it('has no /ceo page and no CEO entry in the sidebar', () => {
    const routes = files.filter((file) => file.name.endsWith(`${sep}routes.ts`))
    expect(routes.length).toBeGreaterThan(5)
    for (const file of routes) {
      expect(file.text, file.name).not.toMatch(/path:\s*['"]\/ceo|ceo-chat|['"]ceo\.nav['"]/)
    }
  })
})
