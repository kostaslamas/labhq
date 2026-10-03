"""Agentless SSH to the hosts labhq watches: a `CommandRunner` over `asyncssh`.

Host keys are checked against a known-hosts file labhq keeps under its data directory, never
the owner's own: `labhq hosts add` records a key only after the owner confirms its
fingerprint, and a key that no longer matches fails the connection.

The client key comes from the owner's SSH agent or from `LABHQ_SSH_KEY_PATH`. Only the
engine opens these connections; worker environments drop the agent socket
(`labhq.worktrees.environment`), and nothing here passes a key to a child process.
"""

import asyncio
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncssh
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from labhq.health.collectors.commands import Argv, CommandResult
from labhq.settings import Settings

DEFAULT_PORT = 22
KNOWN_HOSTS_FILENAME = "known_hosts"


class SshSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABHQ_SSH_", extra="ignore")

    # None uses the owner's SSH agent (and the default identities beside it).
    key_path: Path | None = None
    # None keeps the file under the data directory.
    known_hosts_path: Path | None = None
    connect_timeout_seconds: float = Field(default=15.0, gt=0)
    command_timeout_seconds: float = Field(default=60.0, gt=0)
    # An approved fix (an upgrade, a restart) may run far longer than a probe.
    intervention_timeout_seconds: float = Field(default=1800.0, gt=0)

    def known_hosts(self) -> Path:
        if self.known_hosts_path is not None:
            return self.known_hosts_path
        return Settings().data_dir / KNOWN_HOSTS_FILENAME


class SshError(ConnectionError):
    """The host could not be reached or would not run a command."""


class HostKeyNotTrustedError(SshError):
    """The host presented a key labhq has not recorded: changed, or never added."""


@dataclass(frozen=True)
class SshTarget:
    host: str
    port: int = DEFAULT_PORT

    @classmethod
    def parse(cls, address: str) -> "SshTarget":
        """`host`, `host:port`, `[v6]` or `[v6]:port`."""
        address = address.strip()
        if address.startswith("["):
            host, _, rest = address[1:].partition("]")
            port = rest.removeprefix(":")
        elif address.count(":") == 1:
            host, _, port = address.partition(":")
        else:
            host, port = address, ""
        if not host:
            raise ValueError(f"no host in address {address!r}")
        return cls(host, int(port) if port else DEFAULT_PORT)

    @property
    def pattern(self) -> str:
        """How OpenSSH names this target in a known-hosts file."""
        return self.host if self.port == DEFAULT_PORT else f"[{self.host}]:{self.port}"

    def __str__(self) -> str:
        return self.pattern


def fingerprint(key: asyncssh.SSHKey) -> str:
    return key.get_fingerprint("sha256")


async def fetch_host_key(target: SshTarget, settings: SshSettings) -> asyncssh.SSHKey:
    """The key the host presents now, for the owner to compare before trusting it."""
    try:
        async with asyncio.timeout(settings.connect_timeout_seconds):
            key = await asyncssh.get_server_host_key(target.host, target.port, config=None)
    except (asyncssh.Error, OSError, TimeoutError) as error:
        raise SshError(f"cannot reach {target}: {error or 'timed out'}") from error
    if key is None:
        raise SshError(f"{target} presented no host key")
    return key


def _entries(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def trusted_keys(path: Path, target: SshTarget) -> list[asyncssh.SSHKey]:
    keys = []
    for line in _entries(path):
        fields = line.split()
        if len(fields) >= 3 and fields[0] == target.pattern:
            keys.append(asyncssh.import_public_key(f"{fields[1]} {fields[2]}"))
    return keys


def trust_host_key(path: Path, target: SshTarget, key: asyncssh.SSHKey) -> None:
    """Record `key` as the only one trusted for `target`."""
    kept = [line for line in _entries(path) if line.split()[:1] != [target.pattern]]
    public = key.export_public_key("openssh").decode().split()
    kept.append(f"{target.pattern} {public[0]} {public[1]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(kept) + "\n")


@dataclass(frozen=True)
class SshRunner:
    connection: asyncssh.SSHClientConnection
    timeout_seconds: float

    async def run(self, argv: Argv) -> CommandResult:
        # The remote side always parses a command line; quoting keeps argv intact.
        try:
            result = await self.connection.run(
                shlex.join(argv), check=False, timeout=self.timeout_seconds, errors="replace"
            )
        except asyncssh.Error as error:
            raise SshError(f"{argv[0]} failed over SSH: {error}") from error
        return CommandResult(
            exit_status=result.exit_status if result.exit_status is not None else -1,
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
        )


def _client_options(settings: SshSettings) -> dict[str, Any]:
    if settings.key_path is None:
        return {}
    # An explicit key replaces the agent, so the engine authenticates with that key alone.
    return {"client_keys": [str(settings.key_path)], "agent_path": None}


@asynccontextmanager
async def ssh_runner(
    target: SshTarget, user: str, settings: SshSettings, *, timeout_seconds: float | None = None
) -> AsyncIterator[SshRunner]:
    known_hosts = settings.known_hosts()
    if not trusted_keys(known_hosts, target):
        raise HostKeyNotTrustedError(f"no trusted host key for {target}; run `labhq hosts add`")
    try:
        connection = await asyncssh.connect(
            target.host,
            target.port,
            username=user,
            known_hosts=str(known_hosts),
            # labhq's own settings only; the owner's ~/.ssh/config never redirects a host.
            config=None,
            preferred_auth="publickey",
            connect_timeout=settings.connect_timeout_seconds,
            **_client_options(settings),
        )
    except asyncssh.HostKeyNotVerifiable as error:
        raise HostKeyNotTrustedError(
            f"the host key of {target} does not match the one labhq trusts: {error}"
        ) from error
    except (asyncssh.Error, OSError) as error:
        raise SshError(f"cannot connect to {user}@{target}: {error}") from error
    async with connection:
        yield SshRunner(connection, timeout_seconds or settings.command_timeout_seconds)
