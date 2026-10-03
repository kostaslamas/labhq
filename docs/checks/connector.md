# Manual check: a Claude custom connector reaches labhq through a quick tunnel

CI proves the pieces locally: the adapter against a fake `cloudflared`, JSON (not SSE)
answers from the running server, and the post-start `initialize` check (`tests/expose/`).
Only a real Cloudflare quick tunnel and a real Claude client prove the whole path, so this
is a manual check. Tests never do it (CONTRIBUTING.md section 7).

## What it proves

A Claude custom connector, given the printed URL with the secret path, connects through a
Cloudflare quick tunnel without Cloudflare Access and lists the labhq tools.

## Before you run it

- `cloudflared` is installed (`cloudflared --version`). Without it the command fails with
  an install hint and does not start a local-only server.
- A labhq data directory exists: `uv run labhq init`.
- Port 8787 is free, or pick another with `--port`.
- You have a Claude account that can add a custom connector.

## Run it

1. Start the server with the quick tunnel:

   ```sh
   uv run labhq mcp serve --expose quick-tunnel
   ```

2. Wait for one line: `Connector URL: https://<words>.trycloudflare.com/mcp/<token>`. The
   line appears only after labhq has made an authenticated `initialize` call through the
   public URL. If it fails, the command stops the tunnel and exits non-zero.
3. In Claude, add a custom connector and paste the URL. Leave the authentication fields
   empty: the secret path is the credential.
4. Open a conversation with the connector enabled and ask Claude to list the labhq tools.
5. Stop the server with Ctrl-C. Confirm `pgrep cloudflared` prints nothing.

## Pass criteria

- The connector connects with no Cloudflare login or Access prompt.
- Claude lists the labhq tools (the ones `tools/list` returns locally).
- A request to the same host without the secret path gets `401`:

  ```sh
  curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<words>.trycloudflare.com/mcp
  ```

- The terminal shows the connector URL once and nowhere else.
- After Ctrl-C no `cloudflared` process is left.

## Safety note

labhq starts `cloudflared tunnel --config /dev/null --url http://127.0.0.1:<port>`. The empty
config keeps your own `~/.cloudflared/config.yml` out, so the quick tunnel cannot attach to
a named tunnel that serves other hostnames. If you ever see `cred-file` in the cloudflared
log of this check, stop and report it.

## Record the run

| Date | labhq version | cloudflared version | Claude client | Tools listed | Result |
|---|---|---|---|---|---|
| | | | | | |
