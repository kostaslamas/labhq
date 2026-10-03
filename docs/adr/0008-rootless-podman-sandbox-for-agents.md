# 0008. Run agents in a rootless Podman container when Podman is available

## Status

Accepted (2026-10-03).

## Date

2026-10-03

## Context

Agents run with `bypassPermissions` (plan §5 rule 1) as the owner's OS user. The push guard
has three layers: a parsed-command hook, a disabled push URL and a worker environment
without git credentials. None of them takes away what the user account can reach: an SSH
key file on disk, a credential helper in the user's git config, a token in a config file.
ADR 0005 says it plainly for adopted agents: the layers deter a push, and only a sandbox or
a separate OS user prevents one. Plan §5 rule 6 names the sandbox; nothing builds it yet.

Podman runs containers without a daemon, and rootless: each container lives in the
owner's user namespace, with no root on the host and no long-running service to install.
GitHub's Linux runners ship it, so CI can test the real thing. The `Dockerfile` already
builds an image with the Claude Code binary and the tools a worker needs.

## Options considered

1. bubblewrap (plan §5 rule 6 as written). Light, but Linux only, and every mount and
   namespace rule would be ours to get right.
2. A separate OS user per installation. Strong, but it needs root to create, and a user that
   cannot read the owner's home cannot continue an adopted agent's conversation (ADR 0005).
3. A rootless Podman container per run. No daemon, no root; the same image on Linux, and on
   macOS and Windows through `podman machine`. The mounts are explicit, so what the agent
   can reach is a list we can test.

## Decision

Option 3, as a registry of sandboxes (`none`, `podman`). When rootless Podman is available
(`podman info` reports rootless), `podman` is the default for agents labhq starts; otherwise
`none`, with a warning on the run, as for a missing `rtk`. A setting overrides the choice.

A sandboxed run gets exactly:

- The task worktree, read-write, at the same path, and the repository's common git
  directory, read-write, so commits land on the task branch.
- A labhq-owned Claude configuration directory, mounted as `CLAUDE_CONFIG_DIR`. The owner
  signs in there once with `labhq sandbox login`, which runs the unmodified `claude` login
  flow against that directory. labhq never reads, copies or parses its contents (ADR 0001).
  With `ANTHROPIC_API_KEY` set, the key is passed instead and the directory is not needed.
- The worker environment of the push guard, and nothing else from the host environment.
- Network access, because the agent calls the model. No SSH agent socket, no `~/.ssh`, no
  git credentials, no `gh` token: a push has nothing to authenticate with.

The engine still pushes on the host, after approval, with the owner's own credentials.

Adopted agents (ADR 0005) keep their conversation under the owner's home. They can run in
the sandbox only when the owner moves that conversation into the sandbox configuration
directory; until then they run with `none` and the adoption confirmation says so.

## Consequences

- Plan §5 rule 6 changes from "optional bubblewrap or a separate user" to "rootless Podman
  by default when available". ADR 0005's recommendation points at it.
- New issues: the Podman sandbox, and running `compose.yaml` with Podman as well as Docker.
- CI runs the sandbox tests on Linux, where Podman is installed; elsewhere they are reported
  as not run, never as passed.
- The sandbox image is the `Dockerfile` image; its Claude Code version is the pinned one.
- A run in the sandbox is slower to start than a bare process. Container start time is
  measured and recorded on the run.
