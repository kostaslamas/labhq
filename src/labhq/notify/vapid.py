"""The VAPID key pair that signs every push. Generated once, kept in the data directory."""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid02

KEY_FILENAME = "vapid_private.pem"


def load_or_create_vapid(data_dir: Path) -> Vapid02:
    path = data_dir / KEY_FILENAME
    if path.exists():
        return Vapid02.from_pem(path.read_bytes())
    vapid = Vapid02()
    vapid.generate_keys()
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        # O_EXCL with the mode in `open`: the key is never on disk with wider permissions, and
        # two first starts cannot both write a different key.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return Vapid02.from_pem(path.read_bytes())
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(vapid.private_pem())
    return vapid


def application_server_key(vapid: Vapid02) -> str:
    """The public key as `pushManager.subscribe` wants it: uncompressed point, base64url."""
    point = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode()
