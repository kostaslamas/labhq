import pytest

from labhq.onboard import PlatformInfo, cloudflared_install_command
from labhq.onboard.platforms import family, parse_os_release

RELEASES = "https://github.com/cloudflare/cloudflared/releases/latest/download"


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (PlatformInfo("darwin", "arm64"), "brew install cloudflared"),
        (PlatformInfo("win32", "AMD64"), "winget install --id Cloudflare.cloudflared"),
        (
            PlatformInfo("linux", "x86_64", {"ID": "debian"}),
            f"curl -fsSLo cloudflared.deb {RELEASES}/cloudflared-linux-amd64.deb "
            "&& sudo dpkg -i cloudflared.deb",
        ),
        (
            PlatformInfo("linux", "aarch64", {"ID": "rocky", "ID_LIKE": "rhel centos fedora"}),
            f"curl -fsSLo cloudflared.rpm {RELEASES}/cloudflared-linux-aarch64.rpm "
            "&& sudo rpm -i cloudflared.rpm",
        ),
        (
            PlatformInfo("linux", "x86_64", {"ID": "arch"}),
            f"mkdir -p ~/.local/bin && curl -fsSLo ~/.local/bin/cloudflared "
            f"{RELEASES}/cloudflared-linux-amd64 && chmod +x ~/.local/bin/cloudflared",
        ),
    ],
)
def test_the_install_command_matches_the_platform(info: PlatformInfo, expected: str) -> None:
    assert cloudflared_install_command(info) == expected


def test_a_wsl2_ubuntu_is_a_debian_family() -> None:
    release = parse_os_release('NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n# comment\n')

    assert release == {"NAME": "Ubuntu", "ID": "ubuntu", "ID_LIKE": "debian"}
    assert family(PlatformInfo("linux", "x86_64", release)) == "debian"
