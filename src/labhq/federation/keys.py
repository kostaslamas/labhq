"""Pairing keys: random, shown once, kept only as a hash.

A key is 256 random bits, so a plain SHA-256 is enough to store it: there is nothing to
brute-force, and the hash column is unique, so authentication is an indexed lookup.
"""

import hashlib
import secrets

KEY_PREFIX = "lhqf_"

ORDERS = "orders"
REPORTS = "reports"
ALL_SCOPES = (ORDERS, REPORTS)


def new_key() -> str:
    return f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def looks_like_key(key: str) -> bool:
    return key.startswith(KEY_PREFIX) and len(key) > len(KEY_PREFIX) + 16


def check_scopes(scopes: list[str]) -> list[str]:
    unknown = sorted(set(scopes) - set(ALL_SCOPES))
    if unknown:
        raise ValueError(
            f"unknown scope {', '.join(unknown)}; valid scopes: {', '.join(ALL_SCOPES)}"
        )
    return sorted(set(scopes))
