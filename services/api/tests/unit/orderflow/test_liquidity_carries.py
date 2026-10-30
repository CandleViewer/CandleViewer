"""E21-T04 PR 2 (#710) carries on the pure tracker: the D6 gradual-consume baseline (a), the
call-once cache of `distance_to_liquidity_cluster` (b) and the per-sample event cap (c)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.orderflow.liquidity_models import (
    LiquidityConfig,
    LiquidityConfigInvalid,
    LiquidityPulled,
    LiquidityReload,
)
from tests.unit.orderflow._liquidity_helpers import FakeBook, book, sample, tracker, trade

D = Decimal


def _gradual(prints: bool) -> list[list[LiquidityReload | LiquidityPulled]]:
    """The wall at ask 1002 walks 100 -> 70 -> 40 -> 10 -> 40, 100 ms apart; with `prints`, a
    buy print through it before each step down."""
    t = tracker()
    out = []
    for i, size in enumerate(("100", "70", "40", "10", "40")):
        if prints and i in (1, 2, 3):
            t.on_trade(trade(i * 100 - 10, 1002, "30"))
        out.append(list(sample(t, i * 100, book(size)).events))
    out.append(list(sample(t, 500, book("40")).events))  # the hold for late prints passes
    return out


def test_d6_gradual_consume_then_partial_refill_fires_no_reload() -> None:
    """Carry (a): 100 -> 70 -> 40 -> 10 -> 40 is one consume from 100 and no reload (v1 fired
    `LiquidityReload prior_size=40`)."""
    events = [e for step in _gradual(prints=True) for e in step]
    assert not any(isinstance(e, LiquidityReload) for e in events)
    assert not any(isinstance(e, LiquidityPulled) for e in events)


def test_d6_gradual_consume_measures_the_drop_from_the_baseline() -> None:
    """The consume opens at 40 (60 % below 100); a refill to 90 % of 100 is then the reload."""
    t = tracker()
    assert not sample(t, 0, book("100")).events
    assert not sample(t, 100, book("70")).events  # 30 % down: under consume_pct alone
    t.on_trade(trade(190, 1002, "30"))
    assert not sample(t, 200, book("40")).events
    (r,) = sample(t, 300, book("90")).events
    assert isinstance(r, LiquidityReload)
    assert (r.prior_size, r.replenished_size) == (D(100), D(90))


def test_d6_gradual_pull_without_prints_is_pulled_from_the_baseline() -> None:
    """The same walk with no print: 100 -> 70 -> 40 is one pull from 100 (v1 saw nothing, each
    step being under `consume_pct`); the baseline then restarts at 40, so 40 -> 10 is a second."""
    events = [e for step in _gradual(prints=False) for e in step]
    pulls = [e for e in events if isinstance(e, LiquidityPulled)]
    assert len(pulls) == len(events)
    assert [(e.prior_size, e.remaining_size) for e in pulls] == [(D(100), D(40)), (D(40), D(10))]


def test_d6_baseline_older_than_the_window_rebases_on_the_previous_sample() -> None:
    """A level held at 70 past the window is measured from 70, not from the 100 before it."""
    t = tracker(reload_window_ms=1_000)
    assert not sample(t, 0, book("100")).events
    assert not sample(t, 100, book("70")).events
    assert not sample(t, 1_200, book("70")).events  # 70 is now the level's own size
    assert not sample(t, 1_300, book("40")).events  # 43 % below 70: under consume_pct
    assert not sample(t, 1_400, book("40")).events


def test_d6_growth_raises_the_baseline() -> None:
    t = tracker()
    for i, size in enumerate(("10", "20")):
        assert not sample(t, i * 100, book(size)).events
    t.on_trade(trade(190, 1002, "10"))
    assert not sample(t, 200, book("9")).events  # 55 % below 20
    (r,) = sample(t, 300, book("18")).events
    assert isinstance(r, LiquidityReload) and r.prior_size == D(20)


def _wide(n: int, size: str) -> FakeBook:
    """`n` ask levels from 1001 up, each `size`, and a bid wall."""
    return FakeBook({1000: "50"}, {1001 + i: size for i in range(n)})


def test_event_cap_keeps_the_nearest_and_reports_the_overflow() -> None:
    """Carry (c): a sample emits at most `max_events`, nearest the mid first; the rest are the
    sample's `overflow`, for the caller to count."""
    t = tracker(max_events=3, bands_ticks=(5,))
    sample(t, 0, _wide(10, "10"))
    sample(t, 100, _wide(10, "1"))  # ten drops without prints: held one sample
    res = sample(t, 200, _wide(10, "1"))
    assert [e.price_ticks for e in res.events] == [1001, 1002, 1003]
    assert all(isinstance(e, LiquidityPulled) for e in res.events)
    assert res.overflow == 7


def test_event_cap_not_reached_reports_no_overflow() -> None:
    t = tracker(max_events=16)
    sample(t, 0, _wide(10, "10"))
    sample(t, 100, _wide(10, "1"))
    res = sample(t, 200, _wide(10, "1"))
    assert (len(res.events), res.overflow) == (10, 0)


@pytest.mark.parametrize("bad", [0, 257])
def test_event_cap_is_bounded(bad: int) -> None:
    with pytest.raises(LiquidityConfigInvalid, match="max_events"):
        LiquidityConfig(max_events=bad).validated()


def test_distance_is_computed_once_per_sample_and_cached() -> None:
    """Carry (b): repeated reads in one sample compute once; the next sample clears the cache."""
    t = tracker(bands_ticks=(5,))
    for i in range(20):
        sample(t, i * 100, book("10" if i < 19 else "500"))
    first = t.distance_to_liquidity_cluster()
    assert t.distance_to_liquidity_cluster() == first
    assert t.distance_computes == 1
    t.distance_to_liquidity_cluster("ask")  # another argument set: its own entry
    assert t.distance_computes == 2
    sample(t, 2_000, book("500"))
    t.distance_to_liquidity_cluster()
    t.distance_to_liquidity_cluster()
    assert t.distance_computes == 3


def test_distance_cache_is_bounded_per_sample() -> None:
    t = tracker()
    sample(t, 0, book("10"))
    for z in range(10):
        t.distance_to_liquidity_cluster(z=float(z))
    assert len(t._distance) <= 8
