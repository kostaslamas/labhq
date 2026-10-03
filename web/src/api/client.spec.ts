import { describe, expect, it, vi } from 'vitest'

import { createApiClient, isErrorEnvelope, WRITE_HEADER, WRITE_HEADER_VALUE } from './client'

function recordingFetch(response: () => Response) {
  const requests: Request[] = []
  const fetch = vi.fn((input: Request) => {
    requests.push(input)
    return Promise.resolve(response())
  })
  return { fetch: fetch as unknown as typeof globalThis.fetch, requests }
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

describe('API client', () => {
  it('reads with the session cookie and without the write header', async () => {
    const { fetch, requests } = recordingFetch(() => json(200, { version: '0.0.0' }))
    const client = createApiClient('http://labhq.test', fetch)

    const { data } = await client.GET('/api/health')

    expect(data?.version).toBe('0.0.0')
    expect(requests[0]?.url).toBe('http://labhq.test/api/health')
    expect(requests[0]?.credentials).toBe('same-origin')
    expect(requests[0]?.headers.has(WRITE_HEADER)).toBe(false)
  })

  it.each(['POST', 'PUT', 'PATCH', 'DELETE'])('adds the write header on %s', async (method) => {
    const { fetch, requests } = recordingFetch(() => json(200, {}))
    const client = createApiClient('http://labhq.test', fetch)

    await client.request(method.toLowerCase() as 'post', '/api/health' as never)

    expect(requests[0]?.method).toBe(method)
    expect(requests[0]?.headers.get(WRITE_HEADER)).toBe(WRITE_HEADER_VALUE)
  })

  it('types a failure as the error envelope', async () => {
    const envelope = { error: { code: 'unauthorized', message: 'Sign in to continue.' } }
    const { fetch } = recordingFetch(() => json(401, envelope))
    const client = createApiClient('http://labhq.test', fetch)

    const { data, error, response } = await client.GET('/api/vocabulary')

    expect(data).toBeUndefined()
    expect(response.status).toBe(401)
    expect(error?.error.code).toBe('unauthorized')
    expect(isErrorEnvelope(error)).toBe(true)
  })

  it('tells an envelope from anything else', () => {
    expect(isErrorEnvelope({ error: { code: 'x', message: 'y' } })).toBe(true)
    expect(isErrorEnvelope({ error: 'x' })).toBe(false)
    expect(isErrorEnvelope(null)).toBe(false)
    expect(isErrorEnvelope({ detail: 'x' })).toBe(false)
  })
})
