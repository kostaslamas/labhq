"""A fake `cloudflared tunnel --url URL`: prints a trycloudflare.com URL and really tunnels.

It is an HTTPS proxy on `FAKE_TUNNEL_PROXY_PORT`: a client with `HTTPS_PROXY` pointing at it
and `SSL_CERT_FILE` trusting the fake CA (see certs.py) sends CONNECT, gets TLS with the
`*.trycloudflare.com` leaf, and its bytes reach the `--url` target. Standard library only.

Variables: FAKE_TUNNEL_PROXY_PORT, FAKE_TUNNEL_CERTS (the certs.py directory),
FAKE_TUNNEL_MODE (`forward`, or `silent`: print the URL but answer nothing),
FAKE_CLOUDFLARED_LOG (optional: argv and pid are written there).
"""

import asyncio
import contextlib
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

HOSTNAME = "onboard-check.trycloudflare.com"


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, ssl.SSLError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


def _handler(target: tuple[str, int], tls: ssl.SSLContext):  # type: ignore[no-untyped-def]
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            await writer.start_tls(tls)
            upstream_reader, upstream_writer = await asyncio.open_connection(*target)
        except (OSError, ssl.SSLError, asyncio.IncompleteReadError):
            writer.close()
            return
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))

    return handle


async def main(argv: list[str]) -> None:
    url = urlsplit(argv[argv.index("--url") + 1])
    target = (url.hostname or "127.0.0.1", url.port or 80)
    if log := os.environ.get("FAKE_CLOUDFLARED_LOG"):
        Path(log).write_text(" ".join(argv) + "\n" + str(os.getpid()) + "\n")
    if os.environ.get("FAKE_TUNNEL_MODE", "forward") == "forward":
        certs = Path(os.environ["FAKE_TUNNEL_CERTS"])
        tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        tls.load_cert_chain(certs / "tunnel.pem", certs / "tunnel-key.pem")
        port = int(os.environ["FAKE_TUNNEL_PROXY_PORT"])
        await asyncio.start_server(_handler(target, tls), "127.0.0.1", port)
    sys.stderr.write("INF Requesting new quick Tunnel on trycloudflare.com...\n")
    sys.stderr.write(f"INF |  https://{HOSTNAME}  |\n")
    sys.stderr.flush()
    await asyncio.Event().wait()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(sys.argv[1:]))
