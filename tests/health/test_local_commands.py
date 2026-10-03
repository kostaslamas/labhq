"""The probe scripts run for real on this machine, where the tools they need exist.

Fixtures prove the parsers; these prove the commands themselves, with no network: a
certificate written to disk, and this machine's own `df`.
"""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from labhq.health.collectors import LocalRunner, ProbeContext
from labhq.health.collectors.commands import run_probe
from labhq.health.collectors.procfs import PROCFS_PROBES
from labhq.health.collectors.system import SYSTEM_PROBES

PROBES = {probe.name: probe for probe in (*PROCFS_PROBES, *SYSTEM_PROBES)}
NOW = datetime.now(UTC).replace(microsecond=0)


def needs(*tools: str) -> pytest.MarkDecorator:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    return pytest.mark.skipif(bool(missing), reason=f"needs {', '.join(missing)}")


def write_certificate(path: Path, days: int) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "labhq.test")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


@needs("sh", "openssl")
async def test_the_certificate_script_reads_a_file_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "with space.pem"
    write_certificate(path, days=30)
    context = ProbeContext(
        now=NOW, since=NOW, certificates=(str(path), str(tmp_path / "missing.pem"))
    )

    [reading] = await run_probe(LocalRunner(), PROBES["certificates"], context)

    assert (reading.metric, reading.subject) == ("cert.days_left", str(path))
    assert reading.value == pytest.approx(30.0, abs=0.01)


@needs("df")
async def test_df_on_this_machine_reports_its_disks() -> None:
    readings = await run_probe(LocalRunner(), PROBES["disks"], ProbeContext(now=NOW, since=NOW))
    assert readings
    assert all(0.0 <= reading.value <= 100.0 for reading in readings)
