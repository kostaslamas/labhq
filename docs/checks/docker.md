# Manual check: `docker compose up` on Docker Desktop

CI builds the image and runs `docker compose up --wait` on a Linux runner
(`.github/workflows/docker.yml`): the container turns `healthy`, runs as a non-root user,
publishes on `127.0.0.1` only and answers MCP `tools/list` with the token. Docker Desktop on
macOS or Windows runs the same image in a virtual machine with its own file sharing and
networking, which no CI runner offers, so this is a manual check (CONTRIBUTING.md section 7).

## What it proves

On Docker Desktop, the steps in `docs/guide/docker.md` reach a healthy container whose UI,
MCP endpoint and model login work, and whose data survives a restart.

## Before you run it

- Docker Desktop (macOS, or Windows with the WSL 2 backend), with no `labhq_data` or
  `labhq_home` volume left from an earlier run (`docker volume ls`).
- A directory with at least one git repository, under a path Docker Desktop shares.
- A Claude subscription or an Anthropic API key for the model login step.

## Run it

1. Follow "Install" in `docs/guide/docker.md`: clone, `cp .env.example .env`, set
   `PROJECTS_DIR`, `docker compose up -d`.
2. `docker compose ps` shows `(healthy)` within two minutes. `docker compose exec labhq id -u`
   prints a non-zero id. `docker compose port labhq 8787` prints `127.0.0.1:8787`.
3. Open <http://127.0.0.1:8787> in the browser: the labhq UI loads.
4. `docker compose exec labhq labhq mcp token`, then list the tools from the host:

   ```sh
   npx -y @modelcontextprotocol/inspector@2.9.0 --cli http://127.0.0.1:8787/mcp \
     --transport http --header "Authorization: Bearer <token>" --method tools/list
   ```

5. `docker compose exec labhq claude`: complete the login (or set `ANTHROPIC_API_KEY` in
   `.env` and `docker compose up -d`), then `/exit`.
6. `docker compose exec labhq git -C /projects/<repo> status` works without a "dubious
   ownership" error.
7. `docker compose restart`, wait for `(healthy)`, and confirm the token is the same and
   `docker compose exec labhq claude -p "Reply with OK"` answers without asking for a login.
8. `docker compose down -v`.

## Pass criteria

- The container reaches `healthy` and stays there.
- The UI loads and `tools/list` answers through the published port on `127.0.0.1`.
- The model login persists across a restart.
- git accepts the mounted repositories.

## Record the run

| Date | Host (macOS, Windows) | Docker Desktop version | labhq commit | Time to healthy | Login path | Result |
|---|---|---|---|---|---|---|
