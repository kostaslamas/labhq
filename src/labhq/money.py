"""Cost amounts as integer micro-USD (ADR 0002).

The SDK reports cost as a float. It is converted here, once, through its decimal string
form; no other code path multiplies or compares a float amount.
"""

from decimal import ROUND_HALF_UP, Decimal

MICROS_PER_USD = 1_000_000
_ONE = Decimal(1)


def usd_to_micros(value: float | Decimal | str) -> int:
    """Convert a USD amount to integer micro-USD, rounding half up."""
    if isinstance(value, bool):
        raise TypeError("a boolean is not an amount")
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"amount is not finite: {value!r}")
    if amount < 0:
        raise ValueError(f"amount is negative: {value!r}")
    return int((amount * MICROS_PER_USD).quantize(_ONE, rounding=ROUND_HALF_UP))


def format_micros(micros: int, places: int = 4) -> str:
    """Render micro-USD as dollars with a fixed number of decimals, for display only."""
    if isinstance(micros, bool) or not isinstance(micros, int):
        raise TypeError(f"micros must be an int, got {type(micros).__name__}")
    if not 0 <= places <= 6:
        raise ValueError("places must be between 0 and 6")
    amount = (Decimal(micros) / MICROS_PER_USD).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.{places}f}"
