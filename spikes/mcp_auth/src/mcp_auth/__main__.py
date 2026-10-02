import os

import uvicorn

from mcp_auth.app import build_app, resolve_token

HOST = "127.0.0.1"  # never widen: exposure goes through a tunnel only
DEFAULT_PORT = 8787


def main() -> None:
    token, generated = resolve_token()
    port = int(os.environ.get("LABHQ_SPIKE_PORT", DEFAULT_PORT))
    if generated:
        print(f"Generated token (shown once): {token}")
    # access_log off: the secret-path variant would write the token to the log.
    uvicorn.run(build_app(token), host=HOST, port=port, access_log=False)


if __name__ == "__main__":
    main()
