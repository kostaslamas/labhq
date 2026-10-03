import { vi } from 'vitest'

import { createApiClient, type ApiClient } from '@/api'

export interface Recorded {
  method: string
  path: string
  body: unknown
  headers: Headers
}

type Handler = (request: Recorded) => { status?: number; body?: unknown }

// A fake server for the auth routes: answers by "METHOD /path" and records what was sent.
export function fakeServer(routes: Record<string, Handler>): {
  client: ApiClient
  requests: Recorded[]
} {
  const requests: Recorded[] = []
  const fetch = vi.fn(async (input: Request) => {
    const path = new URL(input.url).pathname
    const text = await input.text()
    const recorded: Recorded = {
      method: input.method,
      path,
      body: text ? (JSON.parse(text) as unknown) : undefined,
      headers: input.headers,
    }
    requests.push(recorded)
    const handler = routes[`${input.method} ${path}`]
    const { status = 200, body = {} } = handler ? handler(recorded) : { status: 404 }
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  return {
    client: createApiClient('http://labhq.test', fetch as unknown as typeof globalThis.fetch),
    requests,
  }
}

export const unauthorized = {
  status: 401,
  body: { error: { code: 'unauthorized', message: 'Sign in to continue.' } },
}
