from decimal import Decimal

import pytest

from labhq.money import format_micros, usd_to_micros


@pytest.mark.parametrize(
    ("usd", "micros"),
    [
        (0.0097, 9700),
        (0.1234565, 123457),
        (0.0172, 17200),
        (0.0, 0),
        (12.5, 12_500_000),
        (Decimal("0.0000015"), 2),
        ("0.0384", 38400),
    ],
)
def test_usd_to_micros_converts_spike_amounts(usd: float | Decimal | str, micros: int) -> None:
    assert usd_to_micros(usd) == micros


def test_usd_to_micros_goes_through_the_decimal_string_not_float_arithmetic() -> None:
    # 5e-07 * 1_000_000 is 0.49999999999999994 in binary floating point, which rounds to 0.
    # Through Decimal(str(value)) it is exactly 0.5, which rounds half up to 1.
    assert round(5e-07 * 1_000_000) == 0
    assert usd_to_micros(5e-07) == 1


def test_usd_to_micros_rounds_half_up_not_to_even() -> None:
    assert usd_to_micros(0.0000025) == 3
    assert usd_to_micros(0.0000035) == 4


def test_usd_to_micros_returns_an_int() -> None:
    assert type(usd_to_micros(0.0097)) is int


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01])
def test_usd_to_micros_rejects_non_finite_and_negative(bad: float) -> None:
    with pytest.raises(ValueError):
        usd_to_micros(bad)


def test_usd_to_micros_rejects_booleans() -> None:
    with pytest.raises(TypeError):
        usd_to_micros(True)


@pytest.mark.parametrize(
    ("micros", "places", "text"),
    [
        (9700, 4, "$0.0097"),
        (123457, 4, "$0.1235"),
        (123457, 6, "$0.123457"),
        (1_234_567_890, 2, "$1,234.57"),
        (0, 4, "$0.0000"),
    ],
)
def test_format_micros_uses_fixed_decimals(micros: int, places: int, text: str) -> None:
    assert format_micros(micros, places) == text


@pytest.mark.parametrize("bad", [0.5, Decimal("1"), True])
def test_format_micros_accepts_only_integer_micros(bad: object) -> None:
    with pytest.raises(TypeError):
        format_micros(bad)  # type: ignore[arg-type]
