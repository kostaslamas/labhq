"""Which origins may run ceremonies, and the relying-party id each one implies.

The relying-party id is the origin's host, so a credential made on `localhost` is useless on
the public host and the other way round. Each origin is enrolled once.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from labhq.auth.errors import AuthError
from labhq.auth.settings import AuthSettings


@dataclass(frozen=True)
class RelyingParty:
    origin: str
    rp_id: str


def relying_party(origin: str | None, settings: AuthSettings) -> RelyingParty:
    if not origin:
        raise AuthError("origin_required", "The request carries no Origin header.")
    parts = urlsplit(origin)
    host = parts.hostname
    # A bare origin only: a path or query would not be what a browser sends.
    if not host or parts.scheme not in {"http", "https"} or parts.path or parts.query:
        raise AuthError("origin_not_allowed", "This origin cannot sign in.")
    normalized = f"{parts.scheme}://{parts.netloc}"
    if normalized == settings.public_url or host in settings.local_hosts:
        return RelyingParty(normalized, host)
    raise AuthError("origin_not_allowed", "This origin cannot sign in.")
