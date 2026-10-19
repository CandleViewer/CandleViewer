"""The C3 Decimal boundary (24-internal-schemas §1.1 C3 and §7.4; SR-E13-12)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.orderflow.errors import IndicatorBoundaryError
from candleviewer.orderflow.indicators import Unavailable, to_decimal
from candleviewer.orderflow.indicators.types import UnavailableReason

Q8 = Decimal("1e-8")


def test_to_decimal_is_decimal_of_str_quantized() -> None:
    assert to_decimal(1.23456789, Decimal("0.0001")) == Decimal("1.2346")
    assert to_decimal(0.1 + 0.2, Q8) == Decimal("0.30000000")  # str(x) is 0.30000000000000004


def test_to_decimal_rounds_half_to_even_once() -> None:
    assert to_decimal(0.125, Decimal("0.01")) == Decimal("0.12")
    assert to_decimal(0.375, Decimal("0.01")) == Decimal("0.38")


def test_to_decimal_returns_a_decimal_with_the_quantum_exponent() -> None:
    value = to_decimal(62_900.0, Q8)
    assert isinstance(value, Decimal)
    assert value.as_tuple().exponent == -8


@pytest.mark.parametrize("reason", ["warmup", "missing", "stale"])
def test_none_never_crosses_as_a_number(reason: UnavailableReason) -> None:
    assert to_decimal(None, Q8) == Unavailable("missing")
    assert to_decimal(None, Q8, if_none=reason) == Unavailable(reason)


@pytest.mark.parametrize("x", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_become_unavailable_nan(x: float) -> None:
    assert to_decimal(x, Q8) == Unavailable("nan")


@pytest.mark.parametrize("x", [-0.0, -1e-12])
def test_a_zero_result_is_unsigned(x: float) -> None:
    value = to_decimal(x, Q8)
    assert isinstance(value, Decimal)
    assert value == 0
    assert not value.is_signed()


def test_the_largest_float_fits_without_signalling() -> None:
    value = to_decimal(1.7976931348623157e308, Q8)
    assert isinstance(value, Decimal)
    assert value.adjusted() == 308


@pytest.mark.parametrize("quantum", [Decimal("NaN"), Decimal("Infinity"), Decimal("1e-81")])
def test_an_unusable_quantum_is_refused(quantum: Decimal) -> None:
    with pytest.raises(IndicatorBoundaryError):
        to_decimal(1.0, quantum)
