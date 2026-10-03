"""Terminal QR codes, for links the owner opens on a phone."""

import io

import segno


def render_qr(data: str) -> str:
    """Half-block characters, so the code fits a terminal and scans from the screen."""
    buffer = io.StringIO()
    segno.make(data, error="m").terminal(out=buffer, compact=True, border=2)
    return buffer.getvalue().rstrip("\n")
