"""LiquidityTracker invariants (E21-T04, #710): ring bound, band monotonicity, the consume
threshold and tape expiry. Derandomised, so a failure reproduces."""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.models import BookPhase
from candleviewer.orderflow.liquidity_models import LiquidityPulled, LiquidityReload
from tests.unit.orderflow._liquidity_helpers import FakeBook, book, sample, tracker, trade

_mid = st.integers(min_value=50, max_value=5_000)
_step = st.tuples(_mid, st.booleans(), st.integers(0, 40))


@settings(max_examples=60, deadline=None, derandomize=True)
@given(steps=st.lists(_step, min_size=1, max_size=80))
def test_ring_never_exceeds_its_bound_and_keeps_order(steps: list[tuple[int, bool, int]]) -> None:
    t = tracker(buckets=8, ring_ms=1_000, cadence_ms=100, bucket_ticks=2)  # 10 columns
    size = t.memory_bytes
    last_mid = steps[0][0]
    for i, (mid, live, extra) in enumerate(steps):
        last_mid = mid
        book = FakeBook({mid: "5", mid - 1 - extra: "3"}, {mid + 1: "5", mid + 2 + extra: "3"})
        sample(t, i * 100, book, BookPhase.LIVE if live else BookPhase.DESYNCED)
        assert t.memory_bytes == size
    for bucket in range((last_mid - 12) // 2, (last_mid + 12) // 2):
        s = t.series(bucket)
        assert len(s.ts_us) <= 10
        assert list(s.ts_us) == sorted(s.ts_us)
        assert len(s.ts_us) == len(s.bid) == len(s.ask) == len(s.estimated)


_levels = st.dictionaries(st.integers(1, 60), st.integers(1, 500), min_size=1, max_size=25)


@settings(max_examples=60, deadline=None, derandomize=True)
@given(bids=_levels, asks=_levels)
def test_bands_are_cumulative_monotonic_and_diff_is_bid_minus_ask(
    bids: dict[int, int], asks: dict[int, int]
) -> None:
    t = tracker()
    b = FakeBook(
        {1000 - k: str(q) for k, q in bids.items()}, {1001 + k: str(q) for k, q in asks.items()}
    )
    bands = sample(t, 0, b).bands
    assert [x.band_ticks for x in bands] == list(t.config.bands_ticks)
    for lo, hi in pairwise(bands):
        assert lo.bid <= hi.bid and lo.ask <= hi.ask
    assert all(x.diff == x.bid - x.ask and x.bid >= 0 and x.ask >= 0 for x in bands)
    total_bid, total_ask = (
        sum(map(Decimal, map(str, bids.values()))),
        sum(map(Decimal, map(str, asks.values()))),
    )
    assert bands[-1].bid <= total_bid and bands[-1].ask <= total_ask


@settings(max_examples=80, deadline=None, derandomize=True)
@given(left=st.integers(0, 49), printed=st.integers(0, 12))
def test_a_drop_is_consumed_only_with_prints_at_or_above_the_threshold(
    left: int, printed: int
) -> None:
    """Wall 100 -> `left` (a drop of at least 50 %): pulled iff prints < drop x tolerance (0.1)."""
    t = tracker()
    sample(t, 0, book("100"))
    if printed:
        t.on_trade(trade(10, 1002, str(printed)))
    events = sample(t, 100, book(str(left))).events + sample(t, 200, book(str(left))).events
    pulled = [e for e in events if isinstance(e, LiquidityPulled)]
    assert not any(isinstance(e, LiquidityReload) for e in events)
    assert bool(pulled) == (Decimal(printed) < Decimal(100 - left) * Decimal("0.1"))
    assert all(p.traded_qty == printed for p in pulled)


@settings(max_examples=60, deadline=None, derandomize=True)
@given(age_ms=st.integers(0, 12_000))
def test_prints_outside_the_window_never_explain_a_drop(age_ms: int) -> None:
    """A big buy through the wall explains the drop only while it is inside the 5 s window."""
    t = tracker()
    sample(t, 0, book("10"))
    t.on_trade(trade(100 - age_ms, 1002, "6"))
    events = sample(t, 100, book("3")).events + sample(t, 200, book("3")).events
    if age_ms >= 5_300:
        assert [type(e) for e in events] == [LiquidityPulled]
    elif age_ms <= 4_000:
        assert not events
