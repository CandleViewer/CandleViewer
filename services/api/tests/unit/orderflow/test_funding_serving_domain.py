"""E24-S03 (#778) serving slice, the pure parts (`domain.funding`): the served `annualised_pct`
(22 `getFundingHistory`) and the coverage gaps (22 `FundingPageMeta`). Property tests hold the
invariants the contract states."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from candleviewer.domain.funding import (
    GAP_CAP,
    MINUTES_PER_YEAR,
    fixed_point,
    funding_gaps,
    served_annualised_pct,
)

_MIN_US = 60_000_000
_T0 = 1_700_006_400_000_000  # a recorded settlement (`funding_history_BTCUSDT_8h.json`)


@pytest.mark.parametrize(
    ("rate", "interval", "served"),
    [
        ("0.00008", 480, "8.76"),  # 22's example
        ("0.0001", 480, "10.95"),  # 22's example, the predicted item
        ("0.0000771", 480, "8.44245"),  # the recorded ticker's rate
        ("-0.00004", 480, "-4.38"),  # a recorded negative settlement
        ("0", 240, "0"),
        ("0.00375", 60, "3285"),  # the recorded cap, at a 1 h interval
    ],
)
def test_served_annualised_pct_is_the_rate_times_settlements_per_year_times_100(
    rate: str, interval: int, served: str
) -> None:
    assert fixed_point(served_annualised_pct(Decimal(rate), interval)) == served


@given(
    rate=st.decimals(min_value=Decimal("-0.05"), max_value=Decimal("0.05"), places=8),
    interval=st.sampled_from([60, 120, 240, 480]),
)
def test_served_annualised_pct_is_exact_for_an_8_dp_rate_on_a_venue_interval(
    rate: Decimal, interval: int
) -> None:
    exact = rate * Decimal(MINUTES_PER_YEAR) / Decimal(interval) * 100
    assert served_annualised_pct(rate, interval) == exact
    text = fixed_point(served_annualised_pct(rate, interval))
    assert "e" not in text.lower() and not text.endswith(".") and text != "-0"
    assert Decimal(text) == exact


@given(
    interval=st.sampled_from([60, 240, 480]),
    # One flag per due settlement, kept or missing: a covered part longer than an instant.
    mask=st.lists(st.booleans(), min_size=2, max_size=200),
    lo_shift=st.integers(min_value=0, max_value=3),
    open_tail=st.booleans(),
)
# The lens's falsifying case (B1): nothing stored, an open tail, a covered edge on the grid.
@example(interval=480, mask=[False, False], lo_shift=0, open_tail=True)
@example(interval=60, mask=[False, False], lo_shift=0, open_tail=True)  # the security lens's
@example(interval=60, mask=[False, True, False], lo_shift=2, open_tail=False)
def test_every_missing_settlement_lies_in_a_listed_gap_and_no_gap_is_false(
    interval: int, mask: list[bool], lo_shift: int, open_tail: bool
) -> None:
    step = interval * _MIN_US
    lo = _T0 + lo_shift * _MIN_US  # a covered edge on or off the settlement grid
    first_due = _T0 if lo_shift == 0 else _T0 + step
    due = [first_due + i * step for i in range(len(mask))]
    hi = due[-1]
    stored = [t for t, keep in zip(due, mask, strict=True) if keep]
    missing = [t for t, keep in zip(due, mask, strict=True) if not keep]
    tail = None if open_tail else hi
    gaps = funding_gaps(stored, interval_min=interval, lo_us=lo, hi_us=tail, grid_us=_T0)
    assert len(gaps) <= GAP_CAP
    assert all(a < b for a, b in gaps)
    assert all(gaps[i][1] <= gaps[i + 1][0] for i in range(len(gaps) - 1))  # oldest first
    for t in missing:
        if open_tail and (not stored or t > stored[-1]):
            continue  # the open tail is the next page's to answer for
        assert any(a <= t <= b for a, b in gaps), t  # an edge `t` is a covered edge: not stored
    for a, b in gaps:  # each span holds a missing settlement (joined spans included)
        assert any(a <= t <= b for t in missing), (a, b)


def test_an_off_grid_covered_edge_reports_the_due_settlement_after_it() -> None:
    step = 480 * _MIN_US
    lo = _T0 + 30 * _MIN_US  # half an hour past a settlement time
    # The settlement due at `_T0 + step` is missing; the span is shorter than one interval.
    gaps = funding_gaps([], interval_min=480, lo_us=lo, hi_us=_T0 + step, grid_us=_T0)
    assert gaps == ((lo, _T0 + step),)
    # With no grid known, only a span of at least one interval surely holds a settlement.
    assert funding_gaps([], interval_min=480, lo_us=lo, hi_us=_T0 + step) == ()
    assert funding_gaps([], interval_min=480, lo_us=lo, hi_us=lo + step) == ((lo, lo + step),)
    # Nothing due between an off-grid edge and the next settlement, stored.
    assert funding_gaps([_T0 + step], interval_min=480, lo_us=lo, hi_us=None, grid_us=_T0) == ()


def test_a_settlement_due_on_a_covered_edge_is_a_gap() -> None:
    step = 480 * _MIN_US
    # Covered from a due settlement that is not stored; the next one is stored.
    assert funding_gaps([_T0 + step], interval_min=480, lo_us=_T0, hi_us=_T0 + step) == (
        (_T0, _T0 + step),
    )
    # The covered part ends on a due settlement that is not stored.
    assert funding_gaps([_T0], interval_min=480, lo_us=_T0, hi_us=_T0 + step) == (
        (_T0, _T0 + step),
    )
    # Between two stored neighbours one interval apart nothing is missing.
    assert funding_gaps([_T0, _T0 + step], interval_min=480, lo_us=_T0, hi_us=_T0 + step) == ()
    # A page that resumes after a stored settlement treats it as one.
    assert (
        funding_gaps([_T0 + step], interval_min=480, lo_us=_T0, hi_us=None, lo_is_settlement=True)
        == ()
    )


def test_past_the_cap_the_oldest_gaps_are_joined_into_one_span() -> None:
    step = 60 * _MIN_US
    stored = [_T0 + 2 * i * step for i in range(GAP_CAP + 10)]  # every other one missing
    gaps = funding_gaps(stored, interval_min=60, lo_us=_T0, hi_us=stored[-1])
    assert len(gaps) == GAP_CAP
    # 73 gaps between the 74 stored settlements: the 10 oldest joined into one span.
    assert gaps[0] == (_T0, stored[10])
    assert gaps[1] == (stored[10], stored[11])
