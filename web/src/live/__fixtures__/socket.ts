import type { SocketLike } from '../connection'

/** A WebSocket the test drives by hand: `open`, `send` a server message, `drop`. */
export class FakeSocket implements SocketLike {
  static all: FakeSocket[] = []

  onopen: ((event: Event) => unknown) | null = null
  onmessage: ((event: MessageEvent) => unknown) | null = null
  onclose: ((event: CloseEvent) => unknown) | null = null
  onerror: ((event: Event) => unknown) | null = null
  closedWith: number | null = null

  constructor(readonly url: string) {
    FakeSocket.all.push(this)
  }

  static latest(): FakeSocket {
    const socket = FakeSocket.all.at(-1)
    if (!socket) throw new Error('no socket was created')
    return socket
  }

  open(): void {
    this.onopen?.(new Event('open'))
  }

  send(message: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(message) }))
  }

  invalidate(topic: string, watermark: string): void {
    this.send({ type: 'invalidate', topic, watermark })
  }

  drop(): void {
    this.onclose?.(new CloseEvent('close', { code: 1006 }))
  }

  close(code = 1000): void {
    this.closedWith = code
  }
}
