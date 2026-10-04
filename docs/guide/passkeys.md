# Passkeys: signing in and approving

The web UI has no password. You sign in with a passkey, and a heavy approval asks for the
passkey again at the moment you decide.

## Enroll the first passkey

The first passkey can only be enrolled from the machine labhq runs on:

```sh
labhq passkey enroll
```

The command prints a single-use link. Open it in a browser and follow the prompt. The link
expires after 10 minutes (`LABHQ_AUTH_ENROLLMENT_TTL_SECONDS`) and stops working after one
use; run the command again for a new one. The link carries its token after a `#`, so the
browser never sends it to a server or a proxy log.

Other commands: `labhq passkey list` shows each passkey with its id and address, and
`labhq passkey revoke <id>` revokes one and ends the sessions it opened.

## A passkey belongs to one address

A passkey works only on the host it was made on. One enrolled on `localhost` does not work on
your public host, and the other way round, so each address you sign in from is enrolled once.

To approve from your phone, set `LABHQ_PUBLIC_URL` to the stable address that reaches labhq,
sign in on the desktop, and ask for a link for the public address. The page shows it as a QR
code; scan it with the phone and enroll there.

`labhq serve --public-url <address>` keeps the address in the data directory, as does a
`LABHQ_PUBLIC_URL` it finds. After that, `labhq passkey enroll` prints a link on the public host
even from a shell without the variable; the variable, when set, wins.

The public address has to be stable. A Cloudflare quick tunnel gets a new host every time it
restarts, so a passkey enrolled for it stops working with it, and you would enroll again on
each restart. A stable URL, such as Tailscale Funnel or your own domain, is the supported way
to approve from a phone. See [Exposure](exposure.md).

## Sessions

A successful sign-in sets an `HttpOnly`, `SameSite=Strict` cookie. It is `Secure` everywhere
except loopback. A session ends after 8 hours without a request (`LABHQ_AUTH_SESSION_IDLE_SECONDS`)
and 30 days after sign-in at the latest (`LABHQ_AUTH_SESSION_ABSOLUTE_SECONDS`). The server stores
only a hash of the session token. Requests that change data must also carry an
`X-Labhq-Request: 1` header, which the web app adds.

## Approving heavy actions

A session alone never approves a heavy action. The server issues a challenge for that one
approval (for example `approval:42`) to your session, you answer it with your passkey, and the
decision is accepted once, within `LABHQ_AUTH_CHALLENGE_TTL_SECONDS` (two minutes). A challenge
for one approval does not work for another, and an answer cannot be replayed. Voice and the
connector can request a heavy approval but can never resolve it.
