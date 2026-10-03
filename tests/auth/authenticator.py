"""A software WebAuthn authenticator: ES256, user verification on, attestation `none`.

It produces what a browser hands to the server, so the real py_webauthn verification runs.
"""

import hashlib
import json
import secrets
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04
FLAG_ATTESTED = 0x40


class SoftwareAuthenticator:
    def __init__(self, *, user_verified: bool = True) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.sign_count = 0
        self.user_verified = user_verified

    @property
    def id(self) -> str:
        return bytes_to_base64url(self.credential_id)

    def _flags(self, *, attested: bool) -> int:
        flags = FLAG_USER_PRESENT | (FLAG_USER_VERIFIED if self.user_verified else 0)
        return flags | (FLAG_ATTESTED if attested else 0)

    def _client_data(self, kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}
        ).encode()

    def _cose_key(self) -> bytes:
        numbers = self._key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def create(self, options: dict[str, Any], origin: str) -> dict[str, Any]:
        """Answer `navigator.credentials.create` for the options the server sent."""
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        attested = (
            bytes(16)
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        auth_data = (
            rp_hash + bytes([self._flags(attested=True)]) + struct.pack(">I", self.sign_count)
        ) + attested
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(
                    self._client_data("webauthn.create", options["challenge"], origin)
                ),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(
        self, options: dict[str, Any], origin: str, *, sign_count: int | None = None
    ) -> dict[str, Any]:
        """Answer `navigator.credentials.get`; each call raises the counter unless told."""
        self.sign_count = self.sign_count + 1 if sign_count is None else sign_count
        rp_hash = hashlib.sha256(options["rpId"].encode()).digest()
        auth_data = (
            rp_hash + bytes([self._flags(attested=False)]) + struct.pack(">I", self.sign_count)
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self._key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(b"labhq-owner"),
            },
            "clientExtensionResults": {},
        }


def challenge_bytes(options: dict[str, Any]) -> bytes:
    return base64url_to_bytes(options["challenge"])
