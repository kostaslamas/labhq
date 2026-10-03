"""A throwaway CA and a `*.trycloudflare.com` leaf, so the fake tunnel can speak real TLS.

The client trusts the CA through `SSL_CERT_FILE`, which httpx honours, so labhq verifies the
fake tunnel exactly as it verifies Cloudflare's. Usage: python certs.py OUTPUT_DIR
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_FILE = "ca.pem"
CERT_FILE = "tunnel.pem"
KEY_FILE = "tunnel-key.pem"


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def write_certificates(directory: Path) -> Path:
    """Writes the CA, the leaf and its key into `directory`; returns the CA path."""
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = _name("labhq fake tunnel CA")
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name("fake.trycloudflare.com"))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("*.trycloudflare.com")]), critical=False
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    (directory / CA_FILE).write_bytes(ca.public_bytes(pem))
    (directory / CERT_FILE).write_bytes(leaf.public_bytes(pem))
    (directory / KEY_FILE).write_bytes(
        key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return directory / CA_FILE


if __name__ == "__main__":
    print(write_certificates(Path(sys.argv[1])))
