"""Cloudflare quick tunnel: `cloudflared` publishes a random trycloudflare.com URL."""

import queue
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import IO

from labhq.expose.base import ExposureError

URL_PATTERN = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com")
INSTALL_HINT = (
    "cloudflared is not installed; install it from "
    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ "
    "(for example `brew install cloudflared`), then run this command again"
)
DEFAULT_URL_TIMEOUT_SECONDS = 30.0
STOP_TIMEOUT_SECONDS = 5.0


def tunnel_command(binary: str, port: int) -> list[str]:
    # `--config /dev/null` is a safety requirement: without it cloudflared reads the user's own
    # ~/.cloudflared/config.yml and can attach to a named tunnel that serves other hostnames,
    # answering for all of them with this server.
    return [binary, "tunnel", "--config", "/dev/null", "--url", f"http://127.0.0.1:{port}"]


def find_url(line: str) -> str | None:
    match = URL_PATTERN.search(line)
    return match.group(0) if match else None


@dataclass
class QuickTunnel:
    url: str
    process: subprocess.Popen[str]
    reader: threading.Thread | None = None

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        # The reader sees EOF once the process is gone; closing the pipe earlier would race it.
        if self.reader is not None:
            self.reader.join()
        if self.process.stdout is not None:
            self.process.stdout.close()


def _pump(stream: IO[str], lines: queue.Queue[str | None]) -> None:
    # Keeps draining after the URL is found so cloudflared never blocks on a full pipe.
    for line in stream:
        lines.put(line)
    lines.put(None)


class QuickTunnelAdapter:
    def __init__(
        self, *, binary: str = "cloudflared", url_timeout: float = DEFAULT_URL_TIMEOUT_SECONDS
    ) -> None:
        self.binary = binary
        self.url_timeout = url_timeout

    def open(self, port: int) -> QuickTunnel:
        path = shutil.which(self.binary)
        if path is None:
            raise ExposureError(INSTALL_HINT)
        try:
            # stderr is merged: cloudflared logs the URL there, not on stdout.
            process = subprocess.Popen(
                tunnel_command(path, port),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as error:
            raise ExposureError(f"cannot start cloudflared: {error.strerror or error}") from error
        assert process.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue()
        reader = threading.Thread(target=_pump, args=(process.stdout, lines), daemon=True)
        reader.start()
        tunnel = QuickTunnel(url="", process=process, reader=reader)
        try:
            tunnel.url = self._wait_for_url(lines)
        except ExposureError:
            tunnel.close()
            raise
        return tunnel

    def _wait_for_url(self, lines: queue.Queue[str | None]) -> str:
        while True:
            try:
                line = lines.get(timeout=self.url_timeout)
            except queue.Empty:
                raise ExposureError(
                    f"cloudflared printed no trycloudflare.com URL within "
                    f"{self.url_timeout:g} seconds; check your network and try again"
                ) from None
            if line is None:
                raise ExposureError("cloudflared exited before it printed a public URL")
            if (url := find_url(line)) is not None:
                return url
