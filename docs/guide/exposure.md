# Exposure: a public URL for the connector

Claude or ChatGPT calls the Call Center from their own servers, so the connector needs a URL
they can reach. labhq binds to `127.0.0.1` and never listens on a public interface by itself;
an exposure puts a public HTTPS address in front of it. Whatever you pick, the connector URL
is that address followed by `/mcp/<token>`, and the token is what keeps others out (see
[Security](security.md#the-call-center-connector-and-its-exposure)). labhq checks the token
itself, so no exposure needs Cloudflare Access or another identity provider in front.

| Exposure | Account | URL | Best for |
|---|---|---|---|
| [Cloudflare quick tunnel](#cloudflare-quick-tunnel) | None | New on every start | Trying labhq, onboarding |
| [Tailscale Funnel](#tailscale-funnel) | Tailscale | Stable | Daily use without a domain |
| [Your own domain](#your-own-domain) | A domain and its DNS | Stable, yours | Daily use, corporate networks |

## Cloudflare quick tunnel

The default, because it needs no account. `labhq onboard` opens one, and so does:

```sh
labhq mcp serve --expose quick-tunnel
```

labhq runs `cloudflared tunnel --config /dev/null --url http://127.0.0.1:<port>`. The empty
config keeps your own `~/.cloudflared/config.yml` out, so the quick tunnel can never attach
to a named tunnel of yours. The connector URL is printed only after labhq has made an
authenticated MCP call through the public address; if that call fails, the command stops the
tunnel and exits non-zero rather than leave a server nobody can reach.

The catch: the `*.trycloudflare.com` address is new every time the tunnel starts, so you
paste a new connector URL after each restart. A passkey is bound to the host it was enrolled
on, so one enrolled for a quick tunnel dies with it; see [Passkeys](passkeys.md). Install `cloudflared` from Cloudflare (onboarding
prints the command for your platform).

## Tailscale Funnel

A stable `https://<machine>.<tailnet>.ts.net` address, with one Tailscale sign-in and one
approval in the browser. With Tailscale installed and logged in on the machine that runs
labhq:

```sh
labhq serve                    # listens on 127.0.0.1:8787
tailscale funnel --bg 8787     # publishes it on your ts.net name
tailscale funnel status        # shows the public address
```

The first `tailscale funnel` asks you to enable Funnel for your tailnet and prints the link
to do it. The connector URL is `https://<machine>.<tailnet>.ts.net/mcp/<token>`; print the
token with `labhq mcp token`. `tailscale funnel reset` stops publishing.

## Your own domain

For daily use this is the recommended way. Point a hostname you own at labhq through any of:

- **Cloudflare Tunnel** (a named tunnel, free with a Cloudflare account and a domain on it):

  ```sh
  cloudflared tunnel login
  cloudflared tunnel create labhq
  cloudflared tunnel route dns labhq labhq.example.com
  cloudflared tunnel run --url http://127.0.0.1:8787 labhq
  ```

- **Pangolin**, a self-hosted tunnel on a small VPS of yours: add a resource for
  `labhq.example.com` that targets `http://127.0.0.1:8787` on this machine.
- **A reverse proxy** such as Caddy on a machine with a public address:

  ```text
  labhq.example.com {
      reverse_proxy 127.0.0.1:8787
  }
  ```

Leave the proxy's own authentication off for `/mcp/`: AI apps cannot pass a login page, and
the token already guards the endpoint. The MCP server answers with plain JSON, never
server-sent events, so proxies that buffer responses work too.

### Why your own domain behind corporate networks

Corporate networks often block the domains of tunnel services, `trycloudflare.com` and
`ts.net` among them. Your phone's AI app reaches the connector from the app's servers, so
voice keeps working, but the approval page, passkey login and web UI will not open from inside
that network. A hostname on your own domain is rarely on such a list.

## What is not a default

ngrok's free plan puts a warning page in front of login and approvals and caps requests per
month. Pinggy's free tunnels expire after an hour, and localhost.run and Serveo are not
reliable enough for a connector you use daily. You can still put any of them in front of
`127.0.0.1:8787` yourself.
