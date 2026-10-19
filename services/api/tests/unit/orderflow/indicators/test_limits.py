"""`orderflow/indicators/limits.py` is pinned value by value (E13 threat model SR-E13-01).

A bound moves only in a reviewed diff of this file and `limits.py` together (CODEOWNER: backend +
security). The period bound is SCR-035's "Period must be between 1 and 5000.", which the threat
model's 2026-10-13 sign-off fixed for every period-style parameter.
"""

from __future__ import annotations

from decimal import Decimal

from candleviewer.orderflow.indicators import limits

FRACTIONAL = ("MULTIPLIER", "DEVIATION_PCT", "PSAR_ACCELERATION")


def test_limits_period_is_one_to_5000_per_scr_035() -> None:
    assert (limits.PERIOD_MIN, limits.PERIOD_MAX) == (1, 5000)
    assert type(limits.PERIOD_MIN) is int and type(limits.PERIOD_MAX) is int


def test_limits_fractional_bounds_are_pinned_as_exact_decimals() -> None:
    pinned = {
        "MULTIPLIER": ("0.1", "10", "0.1"),
        "DEVIATION_PCT": ("0", "50", "0.1"),
        "PSAR_ACCELERATION": ("0.001", "1", "0.001"),
    }
    for prefix, (low, high, step) in pinned.items():
        values = [getattr(limits, f"{prefix}_{part}") for part in ("MIN", "MAX", "STEP")]
        assert values == [Decimal(low), Decimal(high), Decimal(step)], prefix
        assert all(type(v) is Decimal for v in values), prefix


def test_limits_every_fractional_range_starts_and_ends_on_its_step() -> None:
    for prefix in FRACTIONAL:
        low, high, step = (getattr(limits, f"{prefix}_{part}") for part in ("MIN", "MAX", "STEP"))
        assert low % step == 0 and high % step == 0 and low < high, prefix


def test_limits_module_holds_exactly_the_pinned_names() -> None:
    fractional = {f"{prefix}_{part}" for prefix in FRACTIONAL for part in ("MIN", "MAX", "STEP")}
    assert {n for n in vars(limits) if n.isupper()} == {"PERIOD_MIN", "PERIOD_MAX", *fractional}
