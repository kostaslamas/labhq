// Playwright global setup: seed a throwaway labhq, serve it with the built UI, stop it after.
//
// `tools/ui_seed.py` fills a temporary data directory through the engine's own services with
// the fake adapter, then `labhq serve` runs on a free loopback port and serves `web/dist`.
// Specs read the server's address from `baseURL` and the seeded ids from `seedSummary()`.
// Nothing leaves the machine: notifications go to a local sink, never to ntfy.sh.

import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const BASE_URL_ENV = 'LABHQ_E2E_BASE_URL'
export const SEED_ENV = 'LABHQ_E2E_SEED'

const HOST = '127.0.0.1'
const STARTUP_TIMEOUT_MS = 60_000
const SHUTDOWN_TIMEOUT_MS = 10_000
const POLL_MS = 250

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
const uiDir = join(repoRoot, 'web', 'dist')

export interface SeedSummary {
  projects: number[]
  agents: number[]
  tasks: number[]
  runs: number[]
  cost_events: number[]
  approvals: { heavy: number; light: number }
  question: number
  incident: number
}

export function seedSummary(): SeedSummary {
  const raw = process.env[SEED_ENV]
  if (!raw) throw new Error(`${SEED_ENV} is unset; run the specs through playwright.config.ts`)
  return JSON.parse(raw) as SeedSummary
}

function listen(server: Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, HOST, () => resolve((server.address() as AddressInfo).port))
  })
}

async function freePort(): Promise<number> {
  const probe = createServer()
  const port = await listen(probe)
  await new Promise((resolve) => probe.close(resolve))
  return port
}

// Accepts whatever the notifier posts, so notifications neither fail nor reach the network.
function notificationSink(): Server {
  return createServer((request, response) => {
    request.resume()
    request.on('end', () => response.writeHead(200).end('{}'))
  })
}

function seed(dataDir: string): string {
  const result = spawnSync('uv', ['run', '--frozen', 'python', '-m', 'tools.ui_seed', dataDir], {
    cwd: repoRoot,
    encoding: 'utf-8',
  })
  if (result.status !== 0) {
    throw new Error(`tools.ui_seed failed (${result.status}):\n${result.stderr}`)
  }
  // The summary is the last line; uv may print its own progress before it.
  return result.stdout.trim().split('\n').at(-1) ?? ''
}

async function waitForHealth(url: string, server: ChildProcess): Promise<void> {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`labhq serve exited with ${server.exitCode}`)
    try {
      const response = await fetch(`${url}/api/health`)
      if (response.ok) return
    } catch {
      // Not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS))
  }
  throw new Error(`labhq serve did not answer ${url}/api/health in ${STARTUP_TIMEOUT_MS} ms`)
}

async function stop(server: ChildProcess): Promise<void> {
  if (server.exitCode !== null || server.signalCode !== null) return
  const exited = new Promise((resolve) => server.once('exit', resolve))
  server.kill('SIGTERM')
  const timer = setTimeout(() => server.kill('SIGKILL'), SHUTDOWN_TIMEOUT_MS)
  await exited
  clearTimeout(timer)
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  if (!existsSync(join(uiDir, 'index.html'))) {
    throw new Error(`no built UI in ${uiDir}; run \`npx vite build\` in web/ first`)
  }
  const root = await mkdtemp(join(tmpdir(), 'labhq-e2e-'))
  const dataDir = join(root, 'data')
  const sink = notificationSink()
  let server: ChildProcess | undefined
  const teardown = async () => {
    if (server) await stop(server)
    await new Promise((resolve) => sink.close(resolve))
    await rm(root, { recursive: true, force: true })
  }

  try {
    const summary = seed(dataDir)
    const sinkPort = await listen(sink)
    const port = await freePort()
    const url = `http://${HOST}:${port}`
    server = spawn(
      'uv',
      ['run', '--frozen', 'labhq', 'serve', '--host', HOST, '--port', String(port)],
      {
        cwd: repoRoot,
        env: {
          ...process.env,
          LABHQ_DATA_DIR: dataDir,
          LABHQ_API_UI_DIR: uiDir,
          LABHQ_NOTIFY_KIND: 'ntfy',
          LABHQ_NOTIFY_NTFY_SERVER: `http://${HOST}:${sinkPort}`,
        },
        // Stdout carries the connector URL with its secret path; logs stay on stderr.
        stdio: ['ignore', 'ignore', 'inherit'],
      },
    )
    await waitForHealth(url, server)
    // Workers start after global setup and inherit these.
    process.env[BASE_URL_ENV] = url
    process.env[SEED_ENV] = summary
  } catch (error) {
    await teardown()
    throw error
  }
  return teardown
}
