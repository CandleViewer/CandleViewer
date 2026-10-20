"""`orderflow/indicators/limits.py` is pinned value by value (E13 threat model SR-E13-01).

A bound moves only in a reviewed diff of this file and `limits.py` together (CODEOWNERS: the
`orderflow/` owners). The period bound is SCR-035's "Period must be between 1 and 5000.", which
the threat model's 2026-10-13 sign-off fixed for every period-style parameter.
"""

from __future__ import annotations

from decimal import Decimal

from candleviewer.bars.limits import MAX_TAIL
from candleviewer.orderflow.indicators import limits
from candleviewer.ws.topics import FAMILIES

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


#: SR-E13-03 (instances: 8 per user, 32 per symbol, 128 per process, 30 s grace, swept at most a
#: second after it), SR-E13-04 (a window of at most 250 000 bars, 2 recomputes at once, each read
#: bounded), C-2.17 (a recompute's read pages and fold chunks) and an instance's own state (its
#: points, checkpoint spacing, longest filled gap and staleness).
CAPS = {
    "INSTANCE_CAP_PER_USER": 8,
    "INSTANCE_CAP_PER_SYMBOL": 32,
    "INSTANCE_CAP_PROCESS": 128,
    "INSTANCE_GRACE_US": 30_000_000,
    "SWEEP_EVERY_US": 1_000_000,
    "MAX_WINDOW_BARS": 250_000,
    "MAX_CONCURRENT_RECOMPUTES": 2,
    "RECOMPUTE_TIMEOUT_S": 5.0,
    "HISTORY_PAGE_ROWS": 1_000,
    "PRIME_CHUNK_BARS": 512,
    "MAX_POINTS": 1_000,
    "CHECKPOINT_EVERY": 8,
    "MAX_FILL_SLOTS": 1_000,
    "STALE_AFTER_BARS": 2,
}


def test_limits_instance_and_recompute_caps_are_pinned_per_sr_e13_03_and_04() -> None:
    assert {name: getattr(limits, name) for name in CAPS} == CAPS
    assert all(type(getattr(limits, n)) is type(v) for n, v in CAPS.items())


def test_limits_max_points_is_the_ws_history_cap_and_the_series_store_tail() -> None:
    """An instance keeps as many points as a snapshot may ask for (23 §6.1) and the series store
    holds closed bars (`bars.limits.MAX_TAIL`): `limits` may not import `bars`, so this pins the
    copy."""
    assert limits.MAX_POINTS == MAX_TAIL == FAMILIES["indicators"].options["history"].hi


def test_limits_module_holds_exactly_the_pinned_names() -> None:
    fractional = {f"{prefix}_{part}" for prefix in FRACTIONAL for part in ("MIN", "MAX", "STEP")}
    pinned = {"PERIOD_MIN", "PERIOD_MAX", *fractional, *CAPS}
    assert {n for n in vars(limits) if n.isupper()} == pinned
