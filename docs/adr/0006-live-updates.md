# 0006. Live updates over a WebSocket that carries invalidations

## Status

Accepted (2026-10-03).

## Date

2026-10-03

## Context

The UI must show new approvals, tasks, runs, costs, questions and incidents without a reload.
Plan §8.4 leaves the transport to Phase 4: Server-Sent Events or a WebSocket. Four facts
decide it:

- **The quick tunnel does not carry SSE.** The Cloudflare quick tunnel buffers streamed
  responses, so a `text/event-stream` never reaches the browser (plan §9.2; the MCP server
  answers in plain JSON for the same reason). The phone approval page is opened through that
  tunnel, and a quick tunnel is the default public URL a fresh install gets. A WebSocket is
  an upgraded connection that `cloudflared` proxies as is, so it crosses the tunnel.
- **One user, a few tabs.** Over HTTP/1.1, which a self-hosted install without TLS
  termination usually speaks, a browser opens at most six connections per origin. Every SSE
  stream holds one for as long as the tab is open, so a few tabs starve the API calls. A
  WebSocket does not come out of that pool.
- **Reconnects through proxies.** Proxies close idle connections: Cloudflare after about
  100 s, nginx and Caddy after 60 s by default. Either transport needs heartbeats. SSE
  reconnects by itself and replays with `Last-Event-ID`; a WebSocket client reconnects in our
  own code. Replay is not needed if a reconnect refetches everything the page shows, which
  is also the only recovery that works after the server restarted and lost its history.
- **FastAPI and uvicorn.** Both support WebSockets natively; uvicorn's `websockets` backend
  is already a declared dependency. SSE would be a streaming response with no additional
  library. Neither choice costs a dependency.

Two more points shape the messages rather than the transport. The CLI, hooks and agents
write to SQLite from other processes, so the server cannot learn of a change from its own
ORM session. And every page already has a REST endpoint with its authorization and its
response shape; a second path that pushes rows would duplicate both.

## Decision

1. **Transport: one WebSocket per tab at `GET /api/live`.** It is authenticated in the
   handshake by the API foundation's `current_owner`, through the same session resolvers as
   every other route; an unauthenticated handshake is closed with policy violation (1008)
   before it is accepted. The client sends nothing.
2. **Messages are invalidations, never data:** `{"type": "invalidate", "topic": ...,
   "watermark": ...}`. The watermark is opaque and compared only for equality. The client
   refetches the topic through the normal API. When nothing has changed for
   `LABHQ_LIVE_HEARTBEAT_SECONDS` (default 20 s) the server sends `{"type": "heartbeat"}`.
3. **Change feed by polling watermarks.** A loop of the always-on program reads one cheap
   aggregate row per topic (highest id, row count, latest instants, rows per status) every
   `LABHQ_PROGRAM_LIVE_INTERVAL_SECONDS` (default 1 s) and publishes the topics whose
   watermark moved to an in-process broker. Polling the database sees commits from every
   process. A failing query is logged and retried on the next pass; other topics go on.
4. **Topics are a registry** (`labhq.live.registry`): a name and its watermark query. A new
   topic is one registration; the broker and the endpoint never change for it.
5. **The broker coalesces.** Each socket keeps only the newest watermark per topic, so a slow
   tab costs at most one entry per topic, never a growing queue.
6. **The client** (`web/src/live/`) keeps one socket for all subscriptions of the tab,
   reconnects with exponential backoff and jitter (1 s doubling to 30 s), treats 45 s of
   silence as a dead link, and after every reconnect refetches every subscribed topic, so
   nothing is missed while offline.

## Consequences

- Live updates work behind the quick tunnel, Tailscale Funnel, a Cloudflare Tunnel and the
  usual reverse proxies; the proxy must allow the WebSocket upgrade on `/api/live` (Caddy
  and Cloudflare do by default, nginx needs the `Upgrade` and `Connection` headers).
- An update reaches the UI at most one interval plus a request later. That is the price of
  seeing other processes' writes without triggers or a message bus.
- The feed runs some fixed number of aggregate queries per second, one per topic. They read
  indexed columns of small tables; if a table outgrows that, its topic changes its query,
  not the design.
- The broker lives in the `labhq serve` process. A second API process would need its own
  feed loop, which is cheap, or a shared broker, which is not planned.
- Row data never travels on the socket, so the socket cannot leak what a route would refuse.
