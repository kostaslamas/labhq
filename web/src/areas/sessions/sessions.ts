import { isErrorEnvelope, type components } from '@/api'
import { authClient } from '@/auth/client'

export type SessionsView = components['schemas']['SessionsOut']
export type ScannedProject = components['schemas']['ScannedProject']
export type ScannedSession = components['schemas']['SessionOut']
export type Requested = components['schemas']['Requested']

export type Outcome = { ok: true; requested: Requested } | { ok: false; message: string }

const FAILED = 'failed'

export async function loadSessions(): Promise<SessionsView | null> {
  const { data } = await authClient().GET('/api/inventory/sessions')
  return data ?? null
}

/** Run a scan now (no model, no transcript read), then read what it found. */
export async function scanSessions(): Promise<SessionsView | null> {
  const scanned = await authClient().POST('/api/inventory/scan')
  return scanned.data === undefined ? null : loadSessions()
}

// The server's reason is written for the owner; anything else is the generic failure.
function refusal(error: unknown): Outcome {
  const reason = isErrorEnvelope(error) ? error.error.message : FAILED
  return { ok: false, message: reason }
}

async function request(
  call: () => Promise<{ data?: Requested; error?: unknown }>,
): Promise<Outcome> {
  try {
    const { data, error } = await call()
    return data === undefined ? refusal(error) : { ok: true, requested: data }
  } catch {
    return { ok: false, message: FAILED }
  }
}

/** The estimate for analysing one project, and the approval that would start it. */
export function analyse(project: string): Promise<Outcome> {
  return request(() => authClient().POST('/api/inventory/actions/analyse', { body: { project } }))
}

export function closeSession(project: string, pid: number): Promise<Outcome> {
  return request(() =>
    authClient().POST('/api/inventory/actions/close', { body: { project, pid } }),
  )
}

export function continueSession(project: string, session: ScannedSession): Promise<Outcome> {
  const body =
    session.pid !== null
      ? { project, pid: session.pid }
      : { project, session_id: session.session_id }
  return request(() => authClient().POST('/api/inventory/actions/continue', { body }))
}

export function createFolderManager(folder: string): Promise<Outcome> {
  return request(() => authClient().POST('/api/inventory/actions/folder', { body: { folder } }))
}
