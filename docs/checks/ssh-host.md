# Manual check: a remote machine sends metrics over SSH with a read-only user

Acceptance criterion of issue #76 and the Phase 3 demo of plan §10. The tests collect over a
real SSH connection to an in-process server that answers from captured output; this check
proves the same path against a real machine on your network. It needs a second machine, so
the owner runs it; it never runs in CI.

## What it proves

1. A dedicated user with no sudo and no write access collects every metric labhq knows
   that its groups allow.
2. `labhq hosts add` shows the host key's fingerprint and records it only after you
   confirm it.
3. The collector (`labhq health --collect`, or the `health` loop of `labhq serve`) stores
   the remote host's samples next to the local ones.
4. A changed host key stops the collection and is reported; it is never accepted silently.

## On the remote machine

Create the read-only user. It gets no password, no sudo and no shell features beyond running
commands; its key is restricted to the labhq server's address.

```sh
sudo useradd --create-home --shell /bin/sh labhq-ro
sudo passwd --lock labhq-ro
# The full journal, so `journal.errors` counts every unit's errors, not only this user's.
sudo usermod --append --groups systemd-journal labhq-ro   # Debian also accepts `adm`
sudo install -d -m 700 -o labhq-ro -g labhq-ro ~labhq-ro/.ssh
# Replace the key and the address with your labhq server's public key and IP.
echo 'restrict,from="192.0.2.10" ssh-ed25519 AAAA... labhq' \
  | sudo tee ~labhq-ro/.ssh/authorized_keys
sudo chown labhq-ro:labhq-ro ~labhq-ro/.ssh/authorized_keys
sudo chmod 600 ~labhq-ro/.ssh/authorized_keys
```

Do not add the user to `docker` or `disk`: both are root-equivalent (the Docker socket starts
privileged containers; `disk` writes raw block devices). Without them `container.running`
and `smart.healthy` fail on this host, and each costs only its own metric. A host where you
want them needs a deliberate, separate decision, for example a sudoers rule limited to
`smartctl -H`, which this check does not make.

Note the host key fingerprint from the machine's own console, not over the network:

```sh
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

## On the labhq machine

The key comes from your SSH agent, or from a file you name. Only the engine uses it; worker
environments drop `SSH_AUTH_SOCK`.

```sh
ssh-keygen -t ed25519 -f ~/.ssh/labhq_ed25519 -C labhq   # once; its .pub goes above
export LABHQ_SSH_KEY_PATH=~/.ssh/labhq_ed25519
# Optional: certificates to watch on that host, by host name.
export LABHQ_HEALTH_CERTIFICATES='{"nas": ["nas.lan:443"]}'

uv run labhq hosts add nas --address nas.lan --user labhq-ro
# Compare the fingerprint shown with the one from the console, then answer y.
uv run labhq hosts list
uv run labhq hosts test nas
uv run labhq health --collect
uv run labhq health | grep '^nas '
```

Then check that nothing is accepted silently. On the remote machine, regenerate its host
keys (`sudo ssh-keygen -A` after moving the old keys aside, then restart `sshd`), and run
`uv run labhq hosts test nas` again. Put the old keys back afterwards.

## Expected result

- `hosts add` prints `nas (nas.lan) presents ssh-ed25519 key SHA256:...` with the console's
  fingerprint, and `~/.local/share/labhq/known_hosts` (or your `LABHQ_DATA_DIR`) gains one
  line for `nas.lan`.
- `hosts test nas` prints `cpu.percent`, `memory.percent`, `load.1m`, `load.5m`, `load.15m`,
  `disk.percent [/]`, `service.active [...]` for the running units, `journal.errors` and
  `updates.pending`, plus `cert.days_left` when you set certificates.
- `labhq health` lists the same metrics under `nas` with the collection time.
- With the regenerated keys, `hosts test nas` exits 1 with `the host key of nas.lan does not
  match the one labhq trusts`, and `known_hosts` is unchanged. Under `labhq serve` the host
  turns `down` and one `host_key_rejected` notification is queued per day.

## Result

Recorded runs, newest last.

| Date | Remote OS | Metrics seen | Missing (and why) | Changed key refused | Notes |
|---|---|---|---|---|---|
| | | | | | |
