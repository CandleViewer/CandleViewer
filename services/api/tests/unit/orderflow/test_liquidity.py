"""LiquidityTracker (E21-T04, #710): one test per Gherkin scenario plus boundaries."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.orderflow.liquidity_models import (
    LiquidityConfig,
    LiquidityConfigInvalid,
    LiquidityPulled,
    LiquidityReload,
)
from tests.unit.orderflow._liquidity_helpers import FakeBook, book, sample, tracker, trade

D = Decimal


def _consumed_then(t, wall_after: str, *, at_ms: int = 100):  # type: ignore[no-untyped-def]
    """Baseline 10 at 0 ms, a 6-lot buy print through the wall, the wall at 3 at 50 ms, then
    `wall_after` at `at_ms`; returns the last sample."""
    assert not sample(t, 0, book("10")).events
    t.on_trade(trade(40, 1002, "6"))
    assert not sample(t, 50, book("3")).events
    return sample(t, at_ms, book(wall_after))


def test_band_thickness_matches_hand_computed_fixture() -> None:
    """Scenario: Band thickness."""
    t = tracker(bands_ticks=(1, 3, 10))
    b = FakeBook({1000: "2", 998: "3", 995: "5"}, {1002: "1", 1004: "4", 1010: "7"})
    got = [(x.band_ticks, x.bid, x.ask, x.diff) for x in sample(t, 0, b).bands]
    # mid = 1001; bid distances 1, 3, 6; ask distances 1, 3, 9 (edges inclusive, cumulative)
    assert got == [(1, D(2), D(1), D(1)), (3, D(5), D(5), D(0)), (10, D(10), D(12), D(-2))]


def test_band_thickness_half_tick_mid_is_exact() -> None:
    t = tracker(bands_ticks=(1,))
    b = FakeBook({1000: "2", 999: "9"}, {1001: "1"})  # mid 1000.5: both touches at 0.5 ticks
    (band,) = sample(t, 0, b).bands
    assert (band.bid, band.ask) == (D(2), D(1))


def test_reload_flagged_as_estimated() -> None:
    """Scenario: Reload flagged as estimated (consume, then replenish to 90% in the window)."""
    ev = _consumed_then(tracker(), "9").events
    assert len(ev) == 1
    (r,) = ev
    assert isinstance(r, LiquidityReload)
    assert r.estimated is True
    assert (r.side, r.price_ticks, r.price) == ("ask", 1002, D("100.2"))
    assert (r.prior_size, r.replenished_size, r.refill_count) == (D(10), D(9), 1)
    assert r.ts_event == 100_000


def test_reload_refill_count_counts_cycles_inside_the_window() -> None:
    t = tracker()
    assert _consumed_then(t, "9").events[0].refill_count == 1  # type: ignore[union-attr]
    t.on_trade(trade(140, 1002, "6"))
    assert not sample(t, 150, book("3")).events
    (r,) = sample(t, 200, book("9")).events
    assert isinstance(r, LiquidityReload) and r.refill_count == 2


def test_refill_count_restarts_when_the_window_lapses() -> None:
    t = tracker()
    _consumed_then(t, "9")
    t.on_trade(trade(10_000, 1002, "6"))
    sample(t, 10_050, book("3"))
    (r,) = sample(t, 10_100, book("9")).events
    assert isinstance(r, LiquidityReload) and r.refill_count == 1


@pytest.mark.parametrize(("after", "fires"), [("5", True), ("5.1", False)])
def test_consume_threshold_is_inclusive_at_50_percent(after: str, fires: bool) -> None:
    t = tracker()
    sample(t, 0, book("10"))
    t.on_trade(trade(10, 1002, "5"))
    sample(t, 50, book(after))
    # a consumed level returns to 9: a reload only if the first drop counted as consumed
    assert bool(sample(t, 100, book("9")).events) is fires


@pytest.mark.parametrize(("back", "fires"), [("9", True), ("8.9", False)])
def test_replenish_threshold_is_inclusive_at_90_percent(back: str, fires: bool) -> None:
    assert bool(_consumed_then(tracker(), back).events) is fires


@pytest.mark.parametrize(("at_ms", "fires"), [(5_050, True), (5_051, False)])
def test_reload_window_edge_is_inclusive(at_ms: int, fires: bool) -> None:
    # consumed at 50 ms; the window is 5 000 ms
    assert bool(_consumed_then(tracker(), "9", at_ms=at_ms).events) is fires


def test_pulled_is_not_reload() -> None:
    """Scenario: Pulled is not reload (a level disappears with no prints at that price)."""
    t = tracker()
    sample(t, 0, book("10"))
    gone = FakeBook({1000: "20", 999: "5"}, {1001: "4", 1003: "20"})
    assert not sample(t, 100, gone).events  # held one sample for a late print (m1)
    (p,) = sample(t, 200, gone).events
    assert isinstance(p, LiquidityPulled)
    assert p.ts_event == 100_000  # stamped with the drop's sample
    assert p.estimated is True
    assert (p.side, p.price_ticks, p.prior_size, p.remaining_size, p.traded_qty) == (
        "ask",
        1002,
        D(10),
        D(0),
        D(0),
    )
    # coming back later is not a reload: the pull never opened a consume
    assert not sample(t, 300, book("10")).events


@pytest.mark.parametrize(("traded", "consumed"), [("1", True), ("0.9", False)])
def test_tolerance_edge_separates_consumed_from_pulled(traded: str, consumed: bool) -> None:
    t = tracker()  # drop 10 x tolerance 0.1 = 1
    sample(t, 0, book("10"))
    t.on_trade(trade(10, 1002, traded))
    sample(t, 100, book("0.001"))
    ev = sample(t, 200, book("0.001")).events
    assert (not ev) is consumed
    if not consumed:
        assert isinstance(ev[0], LiquidityPulled) and ev[0].traded_qty == D(traded)


def test_prints_through_the_level_count_but_the_wrong_side_or_price_does_not() -> None:
    def pulled(trades) -> bool:  # type: ignore[no-untyped-def]
        t = tracker()
        sample(t, 0, book("10"))
        for tr in trades:
            t.on_trade(tr)
        sample(t, 100, book("1"))
        return bool(sample(t, 200, book("1")).events)

    assert not pulled([trade(10, 1005, "5")])  # a sweep through 1002 consumed it
    assert pulled([trade(10, 1001, "5")])  # below the wall: did not reach it
    assert pulled([trade(10, 1002, "5", side="sell")])  # sells do not lift an ask
    assert pulled([trade(-6_000, 1002, "5")])  # outside the window


def test_duplicate_trade_ids_count_once() -> None:
    t = tracker()
    sample(t, 0, book("10"))
    t.on_trade(trade(10, 1002, "0.6", trade_id="x"))
    t.on_trade(trade(11, 1002, "0.6", trade_id="x"))  # 1.2 if counted twice
    sample(t, 100, book("0.001"))
    (p,) = sample(t, 200, book("0.001")).events
    assert isinstance(p, LiquidityPulled)


def test_bid_side_pulled_and_reload_use_sells() -> None:
    t = tracker()
    sample(t, 0, book(bids={1000: "10"}))
    t.on_trade(trade(10, 998, "6", side="sell"))
    assert not sample(t, 50, book(bids={1000: "3"})).events
    (r,) = sample(t, 100, book(bids={1000: "10"})).events
    assert isinstance(r, LiquidityReload) and r.side == "bid"


def test_small_levels_are_ignored_below_min_size() -> None:
    t = tracker()  # min_size = 10 x 0.001
    sample(t, 0, book("0.009"))
    assert not sample(t, 100, book("0.001")).events


def test_estimated_data_is_excluded_during_resync() -> None:
    """Scenario: Estimated data is excluded during resync."""
    t = tracker()
    sample(t, 0, book("10"))
    gap = sample(t, 100, book("1"), BookPhase.DESYNCED)
    assert gap.estimated and gap.events == () and gap.bands == ()
    # the first live sample after the gap re-baselines: the 10 -> 1 drop is not an event
    first = sample(t, 200, book("1"))
    assert not first.estimated and first.events == ()
    assert first.bands  # live again


def test_resync_resets_a_pending_consume() -> None:
    t = tracker()
    sample(t, 0, book("10"))
    t.on_trade(trade(10, 1002, "6"))
    sample(t, 50, book("3"))
    sample(t, 100, book("9"), BookPhase.SNAPSHOT_PENDING)
    assert not sample(t, 150, book("9")).events


def test_one_sided_book_is_a_gap() -> None:
    t = tracker()
    assert sample(t, 0, FakeBook({1000: "1"}, {})).estimated


def test_levels_falling_out_of_the_walk_are_not_pulls() -> None:
    t = tracker()
    sample(t, 0, book("10", bids={1000: "20", 990: "30"}))
    assert not sample(t, 100, book("10", bids={1000: "20"})).events  # 990 left the depth


def test_bounded_memory_old_samples_are_evicted() -> None:
    """Scenario: Bounded memory (200 buckets, 100 ms, more than 10 minutes)."""
    t = tracker()
    before = t.memory_bytes
    assert 9_000_000 < before <= 12 * 1024 * 1024  # the documented per-symbol bound
    b = book("10")
    for i in range(6_050):
        sample(t, i * 100, b)
    s = t.series(1002, 600_000)
    assert t.memory_bytes == before
    assert len(s.ts_us) == 6_000  # evicted, not accumulated
    assert s.ts_us[0] == 50 * 100_000 and s.ts_us[-1] == 6_049 * 100_000
    assert (s.ask == 10).all() and (s.bid == 0).all()


def test_series_window_and_unknown_bucket() -> None:
    t = tracker()
    assert len(t.series(1002).ts_us) == 0  # nothing sampled yet
    for i in range(30):
        sample(t, i * 100, book("10"))
    assert len(t.series(1002, 1_000).ts_us) == 11  # latest 1 s, edges inclusive
    assert len(t.series(5_000_000).ts_us) == 0  # not in the ring


def test_ring_rows_are_wiped_when_the_price_moves_away() -> None:
    t = tracker(buckets=8)
    sample(t, 0, book("10"))  # buckets 997..1004 hold 1002
    sample(t, 100, FakeBook({2000: "1"}, {2001: "1"}))  # the mid moved: rows recycled
    assert len(t.series(1002).ts_us) == 0
    new = t.series(2001)  # history before the row was claimed reads NaN, never the old price
    assert len(new.ts_us) == 2 and bool(new.ask[0] != new.ask[0]) and new.ask[1] == 1


def test_distance_to_liquidity_cluster_finds_the_wall_and_honours_estimated() -> None:
    t = tracker(buckets=64)
    assert t.distance_to_liquidity_cluster() is None  # no history
    b = FakeBook(
        {1000: "1", 999: "1", 998: "1"},
        {1001: "1", 1002: "1", 1003: "1", 1004: "1", 1005: "1", 1006: "1", 1008: "50"},
    )
    for i in range(10):
        sample(t, i * 100, b)
    assert (
        t.distance_to_liquidity_cluster("ask") == 8
    )  # wall at 1008; the mid rounds down to tick 1000
    assert t.distance_to_liquidity_cluster("bid") is None  # no bid cell is a cluster
    sample(t, 1_000, b, BookPhase.DESYNCED)
    assert t.distance_to_liquidity_cluster("ask") is None  # an estimated sample contributes


def test_events_are_deterministic() -> None:
    def run() -> list[object]:
        return [e.model_dump() for e in _consumed_then(tracker(), "9").events]

    assert run() == run()


def test_config_validation_names_the_field() -> None:
    assert LiquidityConfig().validated().samples == 6_000
    for bad in (
        {"bands_ticks": ()},
        {"bands_ticks": (10, 5)},
        {"reload_consume_pct": D(0)},
        {"reload_replenish_pct": D("1.1")},
        {"tolerance_pct": D(-1)},
        {"reload_window_ms": 0},
        {"min_size": D(-1)},
        {"buckets": 257},
        {"bucket_ticks": 0},
        {"cadence_ms": 0},
        {"max_levels": 0},
    ):
        with pytest.raises(LiquidityConfigInvalid):
            LiquidityConfig(**bad).validated()  # type: ignore[arg-type]


def test_late_print_turns_a_pending_pull_into_a_consume() -> None:
    """m1: a print stamped before the drop but delivered after its sample is not a pull."""
    t = tracker()
    sample(t, 0, book("10"))
    assert not sample(t, 100, book("3")).events  # the book change beat the print
    t.on_trade(trade(90, 1002, "6"))  # ts before the sample, delivered after it
    assert not sample(t, 200, book("3")).events  # no pulled event, ever
    (r,) = sample(t, 300, book("9")).events
    assert isinstance(r, LiquidityReload) and r.prior_size == D(10)


@pytest.mark.parametrize("side", ["ask", "bid"])
def test_wall_consumed_to_zero_and_refilled_is_a_reload(side: str) -> None:
    """M1: the level leaves the book entirely, then comes back."""
    t = tracker()
    kind, tick = ("sell", 998) if side == "bid" else ("buy", 1002)

    def wall(qty: str | None) -> FakeBook:
        w = {} if qty is None else {999 if side == "bid" else 1002: qty}
        if side == "bid":
            return FakeBook({1000: "20", 998: "5", **w}, {1001: "4"})
        return FakeBook({1000: "20"}, {1001: "4", 1003: "20", **w})

    sample(t, 0, wall("10"))
    t.on_trade(trade(10, tick, "11", side=kind))
    assert not sample(t, 100, wall(None)).events  # gone entirely
    (r,) = sample(t, 200, wall("10")).events
    assert isinstance(r, LiquidityReload) and r.side == side
    assert (r.prior_size, r.replenished_size, r.refill_count) == (D(10), D(10), 1)


def test_tape_is_bounded_and_expires() -> None:
    from candleviewer.orderflow.liquidity import TAPE_MAX

    t = tracker()
    for i in range(TAPE_MAX + 50):
        t.on_trade(trade(0, 1002 + i % 7, "1"))  # one instant: only the cap evicts
    assert len(t._tape_q["buy"]) == TAPE_MAX
    assert sum(t._tape_qty["buy"].values()) == TAPE_MAX
    sample(t, 10_000_000, book("10"))  # far past the window: everything expires
    assert not t._tape_q["buy"] and not t._tape_qty["buy"]
