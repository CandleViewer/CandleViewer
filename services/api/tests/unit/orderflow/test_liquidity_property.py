"""LiquidityTracker ring invariants (E21-T04, #710): bounded, ordered, evicting."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.models import BookPhase
from tests.unit.orderflow._liquidity_helpers import FakeBook, sample, tracker

_mid = st.integers(min_value=50, max_value=5_000)
_step = st.tuples(_mid, st.booleans(), st.integers(0, 40))


@settings(max_examples=60, deadline=None)
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
