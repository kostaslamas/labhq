"""Random tokens and the hashes that are stored in their place."""

import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # The tokens are 256 random bits, so a fast hash is enough: there is nothing to brute-force.
    return hashlib.sha256(token.encode()).hexdigest()
