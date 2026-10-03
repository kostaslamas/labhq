"""Run inside the labhq container: `initialize`, then `tools/list`, with the bearer token.

`.github/workflows/docker.yml` pipes this file to the container's Python. It reads the token
from `MCP_TOKEN`, prints the tool names and exits non-zero when the endpoint refuses, answers
something other than a tool list, or misses a tool the Call Center must offer.
"""

import os
import sys

import httpx

URL = os.environ.get("MCP_URL", "http://127.0.0.1:8787/mcp")
# The Call Center's core tools (plan §3.3); the list may grow, never lose these.
REQUIRED = frozenset({"brief", "inbox", "health", "decide", "order", "answer"})
HEADERS = {"accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "labhq-docker-check", "version": "1"},
    },
}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def main() -> int:
    token = os.environ["MCP_TOKEN"]
    headers = {**HEADERS, "authorization": f"Bearer {token}"}
    with httpx.Client(timeout=10) as client:
        unauthorized = client.post(URL, json=INITIALIZE, headers=HEADERS)
        if unauthorized.status_code != httpx.codes.UNAUTHORIZED:
            print(f"without the token: {unauthorized.status_code}, expected 401")
            return 1
        client.post(URL, json=INITIALIZE, headers=headers).raise_for_status()
        listed = client.post(URL, json=LIST, headers=headers)
        listed.raise_for_status()
    names = sorted(tool["name"] for tool in listed.json()["result"]["tools"])
    print("tools:", " ".join(names))
    missing = REQUIRED.difference(names)
    if missing:
        print(f"missing tools: {', '.join(sorted(missing))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
