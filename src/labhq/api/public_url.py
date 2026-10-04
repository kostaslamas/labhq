"""The address a phone reaches labhq at: `LABHQ_PUBLIC_URL`, else a running exposure."""

from labhq.auth.settings import get_auth_settings

# Set by whatever opens an exposure in this process, cleared when it closes.
_exposed_url: str | None = None


def announce_exposure(url: str | None) -> None:
    """Record the running exposure's base URL, or None once it is closed."""
    global _exposed_url
    _exposed_url = url.rstrip("/") if url else None


def current_public_url() -> str | None:
    """The base URL without a trailing slash; None when neither source knows one.

    The configured URL wins: it is the stable address a passkey was enrolled on, while a
    quick tunnel changes host on every start.
    """
    return get_auth_settings().public_url or _exposed_url


def approval_link(approval_id: int) -> str | None:
    base = current_public_url()
    return f"{base}/approve/{approval_id}" if base else None
