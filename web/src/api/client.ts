import createClient, { type Client, type Middleware } from 'openapi-fetch'

import type { components, paths } from './schema'

// The body of every failed response (`labhq.api.errors`): `{ error: { code, message } }`.
export type ErrorEnvelope = components['schemas']['ErrorEnvelope']
export type ApiClient = Client<paths>

// A cross-site form or image cannot set a custom header, so the API refuses writes that
// lack it; together with the SameSite=Strict session cookie this is the CSRF defence.
export const WRITE_HEADER = 'X-Labhq-Request'
export const WRITE_HEADER_VALUE = '1'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export const writeHeader: Middleware = {
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method.toUpperCase())) {
      request.headers.set(WRITE_HEADER, WRITE_HEADER_VALUE)
    }
    return request
  },
}

// Paths in the schema already start with `/api`, so the base URL is the page's own origin.
export function createApiClient(baseUrl = '', fetch?: typeof globalThis.fetch): ApiClient {
  const client = createClient<paths>({
    baseUrl,
    // The session is an HttpOnly cookie; same origin only, so it never leaves the server.
    credentials: 'same-origin',
    ...(fetch ? { fetch } : {}),
  })
  client.use(writeHeader)
  return client
}

export const api = createApiClient()

export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const error = value.error
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { code?: unknown }).code === 'string' &&
    typeof (error as { message?: unknown }).message === 'string'
  )
}
