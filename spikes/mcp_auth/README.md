# MCP auth spike

Minimal MCP server proving the Call Center plumbing without third-party auth.

- Streamable HTTP, stateless, JSON responses (no SSE, so Cloudflare quick tunnels work).
- One read-only tool, `what_time_is_it`: UTC time plus a sentence suitable for reading aloud.
- Built-in auth: `Authorization: Bearer <token>`, or a secret path `/mcp/<token>`.
- Binds `127.0.0.1` only. Default port 8787 (override with `LABHQ_SPIKE_PORT`); check it is free first
  with `ss -ltn | grep 8787`.

## Run

    cd spikes/mcp_auth
    uv sync
    LABHQ_SPIKE_TOKEN=<token> uv run python -m mcp_auth   # unset: a random token is printed once

Test and lint: `uv run pytest` and `uv run ruff check .`

Endpoints: `http://127.0.0.1:8787/mcp` (header auth) and `http://127.0.0.1:8787/mcp/<token>`.

## Secret-path trade-off

The path variant exists for clients that cannot send custom headers. The token then sits in the
URL, which ends up in proxy and tunnel logs, browser or client history and screenshots. This
server disables its own access log and rewrites the path before the MCP app sees it, but it cannot
control Cloudflare or Tailscale logs. Prefer the header; rotate the token after any test that used
the path.

## Expose for a manual test

Cloudflare quick tunnel. The isolated config is mandatory: without it `cloudflared` reads the
default config and attaches to the live named tunnel, answering for every subdomain.

    cloudflared tunnel --config /dev/null --url http://127.0.0.1:8787

In the log, confirm "Generated Connector ID" appears and no `cred-file` is mentioned. Use the
printed `https://<random>.trycloudflare.com` URL; stop the tunnel when done.

Alternative: `tailscale funnel 8787` (stop with `tailscale funnel reset`).

Host-header (DNS rebinding) checks are disabled in the app because tunnel hostnames vary; the
bearer guard is the protection, so never run it without a token.

## Add as a custom connector in Claude

Per the Claude help article (https://support.claude.com/en/articles/11175166), custom connectors
offer OAuth, "No sign in", and fixed credentials: the guide says you can "add fixed credentials
such as API keys that Claude sends on every request if your MCP server authenticates with an API
key, bearer token, or other fixed credential instead of OAuth". The exact field labels and
whether the credential is sent as `Authorization: Bearer` were not verifiable from the article
text alone; check in the connector dialog. If no header option appears, use the secret-path URL
`https://<host>/mcp/<token>` with "No sign in".

Steps: Settings, Connectors, Add custom connector, enter the URL ending in `/mcp`, set the
credential, save, then enable it in a conversation.

## What to say by voice

- "What time is it? Use the call center connector."
- "Ask the spike server for the current UTC time and read it back to me."

Expected: the tool is called, no write or approval prompt beyond the usual (it is read-only), and
the answer contains the UTC time and "the connection to the call center works".
