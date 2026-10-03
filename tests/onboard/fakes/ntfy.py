"""A fake ntfy server: records each published message and answers a fixed status.

Importable (`start`) for tests, runnable for CI:
python ntfy.py --port N --log FILE [--status S] [--ready FILE].
Standard library only.
"""

import argparse
import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FakeNtfy(ThreadingHTTPServer):
    def __init__(self, port: int, *, status: int = 200, log: Path | None = None) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.status = status
        self.log = log
        self.messages: list[dict[str, str]] = []

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the host's FQDN, which can stall for seconds on macOS.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeNtfy

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()
        message = {
            "topic": self.path.lstrip("/"),
            "title": self.headers.get("Title", ""),
            "body": body,
        }
        if self.server.status < 400:
            self.server.messages.append(message)
            if self.server.log is not None:
                with self.server.log.open("a") as log:
                    log.write(json.dumps(message) + "\n")
        payload = json.dumps({"id": "fake"} if self.server.status < 400 else {"error": "no"})
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


def start(*, status: int = 200) -> FakeNtfy:
    server = FakeNtfy(0, status=status)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--status", type=int, default=200)
    parser.add_argument("--ready", type=Path, help="Touched once the server is listening.")
    args = parser.parse_args()
    server = FakeNtfy(args.port, status=args.status, log=args.log)
    if args.ready is not None:
        args.ready.touch()
    server.serve_forever()
