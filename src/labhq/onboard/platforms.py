"""The owner's platform, and the one command that installs `cloudflared` on it.

Onboarding never runs these commands: it prints the one for this machine. Each platform
family is a row; a new one is a new row, never a new branch.
"""

import platform
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

OS_RELEASE = Path("/etc/os-release")
RELEASES = "https://github.com/cloudflare/cloudflared/releases/latest/download"
DOWNLOADS_PAGE = (
    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
)


@dataclass(frozen=True)
class PlatformInfo:
    system: str  # `sys.platform`
    machine: str  # `platform.machine()`
    os_release: Mapping[str, str] = field(default_factory=dict)


def parse_os_release(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and not key.startswith("#"):
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


def detect_platform() -> PlatformInfo:
    try:
        release = parse_os_release(OS_RELEASE.read_text(encoding="utf-8"))
    except OSError:
        release = {}
    return PlatformInfo(sys.platform, platform.machine(), release)


SYSTEM_FAMILIES = {"darwin": "macos", "win32": "windows"}
# `ID` and `ID_LIKE` values from /etc/os-release; WSL2 distributions report theirs too.
LINUX_FAMILIES = {
    "debian": "debian",
    "ubuntu": "debian",
    "fedora": "rpm",
    "rhel": "rpm",
    "centos": "rpm",
    "rocky": "rpm",
    "almalinux": "rpm",
    "amzn": "rpm",
}
DEB_ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
RPM_ARCHITECTURES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}


def family(info: PlatformInfo) -> str:
    if info.system in SYSTEM_FAMILIES:
        return SYSTEM_FAMILIES[info.system]
    ids = [info.os_release.get("ID", ""), *info.os_release.get("ID_LIKE", "").split()]
    return next((LINUX_FAMILIES[name] for name in ids if name in LINUX_FAMILIES), "linux")


def _package(kind: str, architectures: Mapping[str, str], installer: str) -> Callable[[str], str]:
    def command(machine: str) -> str:
        arch = architectures.get(machine.lower(), machine.lower())
        name = f"cloudflared.{kind}"
        return (
            f"curl -fsSLo {name} {RELEASES}/cloudflared-linux-{arch}.{kind} "
            f"&& sudo {installer} {name}"
        )

    return command


def _binary(machine: str) -> str:
    arch = DEB_ARCHITECTURES.get(machine.lower(), machine.lower())
    target = "~/.local/bin/cloudflared"
    return (
        f"mkdir -p ~/.local/bin && curl -fsSLo {target} {RELEASES}/cloudflared-linux-{arch} "
        f"&& chmod +x {target}"
    )


CLOUDFLARED_INSTALLERS: dict[str, Callable[[str], str]] = {
    "macos": lambda machine: "brew install cloudflared",
    "windows": lambda machine: "winget install --id Cloudflare.cloudflared",
    "debian": _package("deb", DEB_ARCHITECTURES, "dpkg -i"),
    "rpm": _package("rpm", RPM_ARCHITECTURES, "rpm -i"),
    "linux": _binary,
}


def cloudflared_install_command(info: PlatformInfo) -> str:
    return CLOUDFLARED_INSTALLERS[family(info)](info.machine)
