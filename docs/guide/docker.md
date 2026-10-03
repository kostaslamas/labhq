# Docker: labhq with `docker compose up`

```sh
cp .env.example .env      # then set PROJECTS_DIR
docker compose up -d
```

That builds one image and starts one container that runs `labhq serve`: the web UI, the API,
the MCP endpoint for the Call Center, the scheduler and notifications. The container is healthy
when its database is at the latest migration and its server answers; `docker compose ps` shows
it.

The image holds labhq with its built UI, `git`, `tmux`, `cloudflared` and the Claude Code
binary at the version labhq is tested with. It carries no Node. It runs as the user `labhq`,
never as root, and compose publishes its port on your machine's `127.0.0.1` only.

## Install

You need Docker Engine 25 or later with the Compose plugin 2.24 or later. Docker Desktop
ships both.

1. Clone the repository and enter it:

   ```sh
   git clone https://github.com/kostaslamas/labhq.git
   cd labhq
   ```

2. Copy the settings template and set `PROJECTS_DIR` to the directory that holds the git
   repositories labhq will work on. On Linux, also set `CONTAINER_UID` and `CONTAINER_GID` to
   the output of `id -u` and `id -g`, so that git inside the container accepts the
   repositories and the files agents write belong to you.

   ```sh
   cp .env.example .env
   ```

3. Build and start:

   ```sh
   docker compose up -d
   docker compose ps          # STATUS shows (healthy) after a few seconds
   ```

4. Open <http://127.0.0.1:8787>. `HOST_PORT` in `.env` picks a different host port.

The repositories appear inside the container under `/projects`. Register one with its path
there:

```sh
docker compose exec labhq labhq project add site --repo /projects/site
```

## Model login

labhq never handles your login (ADR 0001). The agents run the Claude Code binary in the
container, which uses one of two logins:

- **Your Claude subscription (default).** Sign in once through Anthropic's own flow:

  ```sh
  docker compose exec labhq claude
  ```

  Follow the prompts, then leave Claude Code with `/exit`. Claude Code keeps its login in the
  container user's home, which is the `home` volume, so it survives restarts and image
  updates. labhq does not read it, copy it or know where it is.

- **An Anthropic API key.** Set `ANTHROPIC_API_KEY` in `.env` and recreate the container with
  `docker compose up -d`. Claude Code then uses API billing. labhq passes this one variable
  through to the agents and nothing else.

A subscription comes with Anthropic's Consumer Terms; you are responsible for staying within
your plan's terms (see ADR 0001 for the reasoning and links).

## Configure

Every setting is an environment variable in `.env`. A variable you leave out stays unset in
the container, so labhq uses its default.

| Variable | Meaning |
|---|---|
| `PROJECTS_DIR` | Required. Host directory with your repositories, mounted at `/projects` |
| `HOST_PORT` | Port on `127.0.0.1` of the host (default 8787) |
| `CONTAINER_UID`, `CONTAINER_GID` | Ids of the container user; match the owner of `PROJECTS_DIR`. Never 0 |
| `ANTHROPIC_API_KEY` | Optional. Switches the agents to API billing |
| `LABHQ_NOTIFY_*` | Optional. Where notifications go, see below |

Changing `CONTAINER_UID` or `CONTAINER_GID` rebuilds the image:
`docker compose up -d --build`.

### Notifications

Web Push is the default. Install the web app on your phone from your public address and enable
notifications in it, see [Notifications](notifications.md). The key pair it signs with lives in
the data volume.

For ntfy, set `LABHQ_NOTIFY_KIND=ntfy`, pick a long random topic, put it in `.env` and subscribe
to the same topic in the ntfy app:

```sh
LABHQ_NOTIFY_KIND=ntfy
LABHQ_NOTIFY_NTFY_TOPIC=labhq-k3v9x2q7m1
```

For Telegram, set `LABHQ_NOTIFY_KIND=telegram`, `LABHQ_NOTIFY_TELEGRAM_TOKEN` and
`LABHQ_NOTIFY_TELEGRAM_CHAT_ID` instead. After `docker compose up -d`, send a test:

```sh
docker compose exec labhq labhq notify test
```

### The MCP connector and exposure

The connector token stays in the data volume. Print it with:

```sh
docker compose exec labhq labhq mcp token
```

On the host, the connector URL is `http://127.0.0.1:8787/mcp/<token>`. Claude or ChatGPT on
your phone needs a public URL. The port is never published beyond `127.0.0.1`; reach it from
outside through an exposure instead:

- **Cloudflare quick tunnel, no account.** `cloudflared` is in the image:

  ```sh
  docker compose exec labhq cloudflared tunnel --config /dev/null --url http://127.0.0.1:8787
  ```

  It prints a `https://…trycloudflare.com` address; the connector URL is that address
  followed by `/mcp/<token>`. The address changes every time the tunnel starts, and the
  tunnel stops with the command.

- **Your own domain or Tailscale.** Point a reverse proxy, Cloudflare Tunnel or Tailscale
  Funnel on the host at `http://127.0.0.1:8787`. For daily use this is the recommended way,
  since many networks block tunnel domains.

## Update

```sh
git pull
docker compose up -d --build
```

The container runs the migrations every time it starts, before the server, so the database
follows the new version by itself. The data and home volumes stay as they are.

## Back up

The `data` volume holds everything labhq knows: the SQLite database and the connector token.
Stop the container so the database is consistent, copy the volume into an archive, and start
again:

```sh
docker compose stop
docker run --rm -v labhq_data:/data:ro -v "$PWD":/backup busybox \
  tar czf /backup/labhq-data.tar.gz -C /data .
docker compose start
```

Restore into a fresh volume the same way, with `tar xzf` into `/data`. The `home` volume holds
the model login made with `docker compose exec labhq claude`. You can leave it out of backups
and log in again after a restore; if you do back it up, keep the archive as safe as a
password.

`docker compose down` keeps both volumes. `docker compose down -v` deletes them, with the
database, the token and the login.

## Docker Desktop on macOS and Windows

Docker Desktop runs the same image in a Linux virtual machine, so everything above applies
with these differences:

- **macOS.** Keep `CONTAINER_UID` and `CONTAINER_GID` at 1000: Docker Desktop maps the
  ownership of bind-mounted files to your macOS user. `PROJECTS_DIR` must be under a
  directory shared with Docker (Settings, Resources, File sharing; your home directory is
  shared by default).
- **Windows.** Use the WSL 2 backend. Keep your repositories inside the WSL distribution, for
  example `PROJECTS_DIR=/home/you/projects`, and run `docker compose` from a WSL shell in the
  cloned repository. Repositories on a Windows drive (`/mnt/c/...`) work, but git is much
  slower there and file modes do not survive.
- On both, Apple silicon and Windows on Arm build the `arm64` image natively; nothing to set.

## Troubleshooting

- **`set PROJECTS_DIR in .env`.** Compose stops before starting anything until `.env` names
  the directory with your repositories.
- **`unhealthy`.** Run the healthcheck by hand to see which condition fails:
  `docker compose exec labhq labhq ready`. It reports the database revision and whether the
  server answers. `docker compose logs labhq` shows the server's own output.
- **`detected dubious ownership` from git.** The container user's id differs from the owner of
  the repositories. Set `CONTAINER_UID` and `CONTAINER_GID` and run
  `docker compose up -d --build`.
- **Port already in use.** Set another `HOST_PORT` in `.env`.
