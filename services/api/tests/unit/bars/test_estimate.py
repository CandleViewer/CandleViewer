"""SR-E12-02 non-time estimate (#2093): exact boundaries per kind, and on random tapes the real
builders never serve more bars in a window than its estimate (renko, which can, is pinned)."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.estimate import estimate_non_time_bars as estimate
from candleviewer.bars.limits import MAX_WINDOW_BARS as CAP
from candleviewer.bars.models import BarBuilder, BarSpec
from candleviewer.bars.renko_builder import RenkoBarBuilder
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from tests.unit.bars._trades import SYM, final_bars, trade

T0 = 1_790_000_000_000_000
TICK100 = BarSpec(kind="tick", tick_count=100)
VOL5 = BarSpec(kind="volume", volume_threshold=Decimal(5))
DELTA2 = BarSpec(kind="delta", delta_threshold=Decimal(2))
RANGE20 = BarSpec(kind="range", range_ticks=20)
RENKO20 = BarSpec(kind="renko", range_ticks=20)
_TENTH = Decimal("0.1")


@pytest.mark.parametrize(
    ("spec", "prints", "qty", "bars"),
    [
        (TICK100, 100 * CAP, Decimal(1), CAP),
        (TICK100, 100 * CAP + 1, Decimal(1), CAP + 1),  # the partial last bar counts
        (BarSpec(kind="tick", tick_count=1), CAP + 1, Decimal(1), CAP + 1),  # N=1: one per print
        (VOL5, 1, Decimal(5 * CAP), CAP),  # one print can close many volume bars
        (VOL5, 1, Decimal(5 * CAP) + Decimal("0.001"), CAP + 1),
        (DELTA2, 10**9, Decimal(2 * CAP), CAP),
        (DELTA2, 10**9, Decimal(2 * CAP + 1), CAP + 1),
        (DELTA2, CAP, Decimal(10**12), CAP),  # never split, so the prints bound it too
        (DELTA2, CAP + 1, Decimal(10**12), CAP + 1),
        (RANGE20, CAP, Decimal(10**12), CAP),
        (RANGE20, CAP + 1, Decimal(1), CAP + 1),
        (RENKO20, CAP + 1, Decimal(1), CAP + 1),
    ],
)
def test_estimate_at_and_one_over_the_cap(
    spec: BarSpec, prints: int, qty: Decimal, bars: int
) -> None:
    assert estimate(spec, prints, qty) == bars


@pytest.mark.parametrize("spec", [TICK100, VOL5, DELTA2, RANGE20, RENKO20])
def test_an_empty_window_estimates_no_bars(spec: BarSpec) -> None:
    assert estimate(spec, 0, Decimal(0)) == 0


def test_huge_totals_stay_exact_past_the_decimal_context() -> None:
    vol3 = BarSpec(kind="volume", volume_threshold=Decimal(3))
    assert estimate(vol3, 1, Decimal(10**40 + 1)) == (10**40 + 2) // 3  # 41 digits > prec 28
    assert estimate(BarSpec(kind="tick", tick_count=7), 10**30 + 1, Decimal(1)) == (10**30 + 6) // 7
    half = BarSpec(kind="volume", volume_threshold=Decimal("0.5"))
    assert estimate(half, 1, Decimal("1.25")) == 3


def test_time_bars_are_not_estimated_from_prints() -> None:
    with pytest.raises(ValueError, match="window span"):
        estimate(BarSpec(kind="time", interval_ms=60_000), 1, Decimal(1))


_FACTORY: dict[str, Callable[[BarSpec], BarBuilder]] = {
    "tick": lambda s: TickBarBuilder(s, SYM),
    "volume": lambda s: VolumeBarBuilder(s, SYM),
    "delta": lambda s: DeltaBarBuilder(s, SYM),
    "range": lambda s: RangeBarBuilder(s, SYM, lambda _s: _TENTH),
}
_SPECS = st.sampled_from(
    [
        BarSpec(kind="tick", tick_count=1),
        BarSpec(kind="tick", tick_count=7),
        BarSpec(kind="volume", volume_threshold=Decimal("0.5")),
        BarSpec(kind="volume", volume_threshold=Decimal(3)),
        BarSpec(kind="delta", delta_threshold=Decimal("0.5")),
        BarSpec(kind="delta", delta_threshold=Decimal(4)),
        BarSpec(kind="range", range_ticks=1),
        BarSpec(kind="range", range_ticks=5),
    ]
)
_PRINTS = st.lists(  # (price in ticks, qty in thousandths > 0, buy)
    st.tuples(st.integers(900, 1_100), st.integers(1, 5_000), st.booleans()),
    min_size=1,
    max_size=120,
)


@settings(max_examples=200, deadline=None)
@given(_SPECS, _PRINTS, st.data())
def test_a_window_of_a_built_series_never_serves_more_bars_than_its_estimate(
    spec: BarSpec, raw: list[tuple[int, int, bool]], data: st.DataObject
) -> None:
    """Print i at T0 + i; the window [T0 + lo, T0 + hi) serves the bars whose row `ts` (open
    time) is inside it, the forming bar included, against the estimate from the prints inside."""
    tape = [trade(T0 + i, Decimal(p) / 10, Decimal(q) / 1000, "buy" if b else "sell", seq=i)
            for i, (p, q, b) in enumerate(raw)]  # fmt: skip
    builder = _FACTORY[spec.kind](spec)
    bars = final_bars(u for t in tape for u in builder.on_trade(t))
    lo = data.draw(st.integers(0, len(tape)))
    hi = data.draw(st.integers(lo, len(tape)))
    served = [b for b in bars if T0 + lo <= b.open_time < T0 + hi]
    qty = sum((t.qty for t in tape[lo:hi]), Decimal(0))
    assert len(served) <= estimate(spec, hi - lo, qty)


def test_renko_takes_the_print_count_which_a_multi_brick_print_exceeds() -> None:
    """Renko uses the print count (#2093) as an estimate, not a bound: here 2 prints make 5
    bricks (one print may complete up to MAX_BRICKS_PER_TRADE, SR-E12-15)."""
    spec = BarSpec(kind="renko", range_ticks=2)
    builder = RenkoBarBuilder(spec, SYM, lambda _s: _TENTH)
    tape = [trade(T0, "100"), trade(T0 + 1, "101", seq=1)]  # +1.0 is 5 bricks of 0.2
    bricks = [b for b in final_bars(u for t in tape for u in builder.on_trade(t)) if b.closed]
    assert len(bricks) == 5 > estimate(spec, len(tape), Decimal(2))
