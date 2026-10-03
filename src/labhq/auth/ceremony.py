"""The WebAuthn ceremonies, as thin wrappers over py_webauthn with user verification required."""

import json
import secrets
from dataclasses import dataclass
from typing import Any

from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from labhq.auth.errors import AuthError
from labhq.auth.origins import RelyingParty
from labhq.db.models import PasskeyCredential

RP_NAME = "labhq"
# One owner, one stable user handle: every passkey belongs to the same person.
USER_HANDLE = b"labhq-owner"
USER_NAME = "owner"
CHALLENGE_BYTES = 32
TIMEOUT_MS = 120_000


@dataclass(frozen=True)
class Options:
    """What the browser is asked to do, and the challenge to keep until it answers."""

    challenge: str
    public_key: dict[str, Any]


def _descriptors(credentials: list[PasskeyCredential]) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential.credential_id))
        for credential in credentials
    ]


def registration_options(rp: RelyingParty, existing: list[PasskeyCredential]) -> Options:
    challenge = secrets.token_bytes(CHALLENGE_BYTES)
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=RP_NAME,
        user_id=USER_HANDLE,
        user_name=USER_NAME,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descriptors(existing),
    )
    return Options(bytes_to_base64url(challenge), json.loads(options_to_json(options)))


def authentication_options(rp: RelyingParty, allowed: list[PasskeyCredential]) -> Options:
    challenge = secrets.token_bytes(CHALLENGE_BYTES)
    options = generate_authentication_options(
        rp_id=rp.rp_id,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        allow_credentials=_descriptors(allowed),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Options(bytes_to_base64url(challenge), json.loads(options_to_json(options)))


@dataclass(frozen=True)
class Registered:
    credential_id: str
    public_key: bytes
    sign_count: int
    transports: list[str]


def verify_registration(credential: dict[str, Any], challenge: str, rp: RelyingParty) -> Registered:
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise AuthError("registration_invalid", "The passkey could not be verified.") from None
    transports = credential.get("response", {}).get("transports", [])
    return Registered(
        bytes_to_base64url(verified.credential_id),
        verified.credential_public_key,
        verified.sign_count,
        [str(item) for item in transports] if isinstance(transports, list) else [],
    )


def verify_assertion(
    assertion: dict[str, Any], challenge: str, rp: RelyingParty, stored: PasskeyCredential
) -> int:
    """Check the signature against the stored key; returns the new sign count.

    py_webauthn refuses a sign count that does not increase (a cloned authenticator), which
    surfaces here as the same `assertion_invalid` as a bad signature.
    """
    try:
        verified = verify_authentication_response(
            credential=assertion,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp.rp_id,
            expected_origin=rp.origin,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise AuthError(
            "assertion_invalid", "The passkey assertion could not be verified."
        ) from None
    return verified.new_sign_count
