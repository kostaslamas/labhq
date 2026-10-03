"""Passkeys and web sessions: WebAuthn enrollment and login, and step-up for heavy decisions.

The API half is `labhq.auth.routes` and `labhq.auth.resolver`; this package stays free of
API imports so the CLI can use it.
"""

from labhq.auth.errors import AuthError
from labhq.auth.settings import AuthSettings, get_auth_settings
from labhq.auth.stepup import begin_step_up, verify_step_up

__all__ = [
    "AuthError",
    "AuthSettings",
    "begin_step_up",
    "get_auth_settings",
    "verify_step_up",
]
