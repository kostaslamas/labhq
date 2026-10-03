# Manual check: `uvx labhq onboard` on a clean machine

CI runs onboarding from the built wheel on fresh Ubuntu and macOS runners against a fake
`cloudflared` and a fake ntfy server (`.github/workflows/onboard.yml`, `tests/onboard/`). Only a
real Cloudflare quick tunnel, the real ntfy.sh, a phone and a real connector prove the whole
path, so this is a manual check, run on clean Linux, macOS and WSL2 machines. Tests never do
it (CONTRIBUTING.md section 7).

## What it proves

On a machine with no labhq data, one `uvx labhq onboard` reaches a working system with no
third-party account: a quick tunnel URL that answers `initialize`, a notification on the
phone through ntfy.sh, and a connector added from the printed QR code.

## Before you run it

- A clean machine or user account: no `LABHQ_*` variables, and no labhq data directory
  (`~/.local/share/labhq` on Linux and WSL2, `~/Library/Application Support/labhq` on macOS).
- `uv` is installed. `cloudflared` is installed, or not, to see the manual step first.
- The ntfy app on your phone, and a Claude (or ChatGPT) account that can add a custom
  connector.
- Optional: Claude Code logged in, or `ANTHROPIC_API_KEY` set.

## Run it

1. Without `cloudflared` on `PATH`, run `uvx labhq onboard --non-interactive --no-serve`.
   It must print exactly one manual step with the install command for this platform, exit
   non-zero, and never print `labhq is ready.`
2. Install `cloudflared` with that command.
3. Run `uvx labhq onboard`. Check that:
   - the ADR 0001 notice appears, with links to the Consumer Terms of Service and the legal
     and compliance page;
   - each step prints what it found and then `ok`;
   - the phone receives "labhq is set up" once you have subscribed (step 4); the test
     notification is already on ntfy.sh, so subscribing afterwards still shows it;
   - it prints the connector URL with a QR code, the ntfy subscribe link with a QR code, and
     `labhq is ready.`, then keeps serving.
4. Scan the ntfy QR code with the phone and subscribe in the ntfy app.
5. Scan the connector QR code with the phone. The decoded text must equal the printed
   connector URL. Add it as a custom connector in Claude (no authentication fields: the
   secret path is the credential), open a conversation and ask for the labhq tools.
6. Stop with Ctrl-C. Confirm `pgrep cloudflared` prints nothing.
7. Run `uvx labhq onboard --no-serve` again. The notice must not appear, the connector token
   and the ntfy topic must be the same (`connector token: kept from an earlier run`,
   `topic kept`), and a second test notification must arrive.

## Pass criteria

- No step asked for an account, a login or a click outside the two QR scans.
- The connector lists the labhq tools through the quick tunnel.
- The test notification arrives on the phone.
- The second run keeps the token and topic, repeats the checks and skips the notice.
- No `cloudflared` process is left after Ctrl-C.

## Record the run

| Date | Machine (Linux, macOS, WSL2) | labhq version | cloudflared version | Connector client | Notification on phone | Result |
|---|---|---|---|---|---|---|
