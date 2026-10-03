"""Step-up: a heavy decision needs a fresh passkey assertion, not just a session.

A session cookie proves the browser signed in earlier. A step-up proves the owner is there
now: the server issues a challenge for one purpose (for example `approval:42`) to one session,
and the decision is accepted only with an assertion over that challenge. A challenge is
single use and expires after `challenge_ttl_seconds`, which is the step-up window.
"""

import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from labhq.auth.authentication import check_assertion, issue_assertion_options
from labhq.auth.errors import AuthError
from labhq.auth.origins import relying_party
from labhq.auth.settings import AuthSettings, get_auth_settings
from labhq.db.models import PasskeyCredential

# `<kind>:<id>`, so the purpose names the one thing the assertion approves.
PURPOSE_PATTERN = re.compile(r"^[a-z][a-z_]{0,31}:[A-Za-z0-9_-]{1,31}$")


def _check_purpose(purpose: str) -> None:
    if not PURPOSE_PATTERN.fullmatch(purpose):
        raise AuthError("purpose_invalid", "A step-up purpose looks like `approval:42`.")


async def begin_step_up(
    db: AsyncSession,
    now: datetime,
    *,
    session_id: int,
    purpose: str,
    origin: str | None,
    settings: AuthSettings | None = None,
) -> dict[str, Any]:
    """Issue the challenge for `purpose` to this session; returns the browser's options."""
    settings = settings or get_auth_settings()
    _check_purpose(purpose)
    rp = relying_party(origin, settings)
    return await issue_assertion_options(
        db, settings, now, rp, purpose=purpose, session_id=session_id
    )


async def verify_step_up(
    db: AsyncSession,
    now: datetime,
    *,
    session_id: int,
    purpose: str,
    assertion: dict[str, Any],
    origin: str | None,
    settings: AuthSettings | None = None,
) -> PasskeyCredential:
    """Accept the assertion once, for `purpose`, in `session_id`'s window; raise otherwise.

    Nothing but a valid assertion passes: the session id only says whose challenge it must be.
    The caller owns the transaction and commits it together with the decision.
    """
    settings = settings or get_auth_settings()
    _check_purpose(purpose)
    rp = relying_party(origin, settings)
    return await check_assertion(db, now, rp, assertion, purpose=purpose, session_id=session_id)
