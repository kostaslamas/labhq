"""Failures of the auth flows. Messages never carry a token, a challenge or an assertion."""

STATUS_BY_CODE: dict[str, int] = {
    "origin_required": 400,
    "origin_not_allowed": 403,
    "malformed_credential": 400,
    "challenge_invalid": 400,
    "enrollment_link_invalid": 400,
    "registration_invalid": 400,
    "assertion_invalid": 401,
    "credential_unknown": 401,
    "credential_revoked": 401,
    "no_passkey": 409,
    "credential_not_found": 404,
    "purpose_invalid": 422,
}


class AuthError(Exception):
    """A refusal with a stable code; the API turns it into the error envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status_code(self) -> int:
        return STATUS_BY_CODE.get(self.code, 400)
