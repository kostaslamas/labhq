"""An in-process `asyncssh` server on 127.0.0.1 that answers probes from captured output.

It runs its own event loop in a thread, so async tests and the synchronous CLI (which runs
`asyncio.run` itself) can both reach it. It executes nothing: each command is answered from
the fixtures, and every login and command is recorded.
"""

import asyncio
import threading
from collections.abc import Coroutine, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import asyncssh

from labhq.health.collectors import CommandResult
from labhq.health.ssh import SshSettings, SshTarget
from tests.health.stubs import answer, captured


class _Server(asyncssh.SSHServer):
    def __init__(self, sshd: "FakeSshd") -> None:
        self._sshd = sshd

    def begin_auth(self, username: str) -> bool:
        return True

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        public = self._sshd.client_key.convert_to_public()
        return username in self._sshd.users and key.public_data == public.public_data


class FakeSshd:
    def __init__(self, users: frozenset[str], answers: Mapping[str, CommandResult]) -> None:
        self.users = users
        self.answers = answers
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.client_key = asyncssh.generate_private_key("ssh-ed25519")
        self.commands: list[tuple[str, str]] = []
        self.port = 0
        self._loop = asyncio.new_event_loop()
        self._acceptor: asyncssh.SSHAcceptor | None = None
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)

    @property
    def target(self) -> SshTarget:
        return SshTarget("127.0.0.1", self.port)

    def _handle(self, process: asyncssh.SSHServerProcess[str]) -> None:
        username = str(process.get_extra_info("username"))
        command = str(process.command or "")
        self.commands.append((username, command))
        result = answer(self.answers, command)
        process.stdout.write(result.stdout)
        process.stderr.write(result.stderr)
        process.exit(result.exit_status)

    async def _start(self) -> None:
        self._acceptor = await asyncssh.create_server(
            lambda: _Server(self),
            "127.0.0.1",
            0,
            server_host_keys=[self.host_key],
            process_factory=self._handle,
        )
        self.port = self._acceptor.sockets[0].getsockname()[1]

    async def _stop(self) -> None:
        if self._acceptor is not None:
            self._acceptor.close()
            await self._acceptor.wait_closed()

    def _call(self, coroutine: Coroutine[Any, Any, None]) -> None:
        asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=30)

    def start(self) -> None:
        self._thread.start()
        self._call(self._start())

    def stop(self) -> None:
        self._call(self._stop())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=30)
        self._loop.close()

    def change_host_key(self) -> None:
        """Present a new key from now on, as a reinstalled or impersonated machine would."""
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")

        async def update() -> None:
            assert self._acceptor is not None
            self._acceptor.update(server_host_keys=[self.host_key])

        self._call(update())

    def client_settings(self, directory: Path) -> SshSettings:
        key_path = directory / "labhq_ed25519"
        self.client_key.write_private_key(key_path)
        return SshSettings(key_path=key_path, known_hosts_path=directory / "known_hosts")


@contextmanager
def running_sshd(
    users: frozenset[str] = frozenset({"labhq-ro"}),
    answers: Mapping[str, CommandResult] | None = None,
) -> Iterator[FakeSshd]:
    sshd = FakeSshd(users, answers if answers is not None else captured())
    sshd.start()
    try:
        yield sshd
    finally:
        sshd.stop()
