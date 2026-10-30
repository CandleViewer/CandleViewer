"""E21-T04 PR 2 (#710): `HeatmapTopic.pin_native` and the native sampler, the liquidity tracker's
one book sampler (carry e): a pinned symbol's native column is built without a lease, each native
deadline hands the sampler the instantaneous levels (never an averaged column), a resync or a late
deadline hands it None, and an un-pinned, unleased symbol is dropped as `_free` drops it. Fake
epoch-ms clock, synthetic levels; no network."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from candleviewer.book.models import BookPhase
from candleviewer.orderflow import heatmap as H
from candleviewer.orderflow.heatmap import COLUMN_MS, DEEP_DEPTH, HeatmapSpec, NativeLevels
from tests.unit.book._builders import delta, lvl, snap
from tests.unit.orderflow.test_heatmap import SYM, T0, Demand, World, ladder, live

Seen = list[tuple[str, int, dict[int, float] | None, dict[int, float] | None]]


def _recorder(w: World) -> Seen:
    seen: Seen = []

    def sampler(symbol: str, t_ms: int, levels: NativeLevels | None) -> None:
        bids = None if levels is None else dict(levels.bids)
        asks = None if levels is None else dict(levels.asks)
        seen.append((symbol, t_ms, bids, asks))

    w.topic.set_sampler(sampler)
    return seen


def _pinned_gauge() -> float:
    return REGISTRY.get_sample_value("heatmap_pinned_symbols") or 0.0


async def test_pinned_symbol_is_sampled_at_every_native_deadline_without_a_lease() -> None:
    w = World()
    await live(w)
    seen = _recorder(w)
    w.topic.pin_native(SYM, 200)
    for k in range(1, 4):
        w.at(k * COLUMN_MS)
    assert [(s, t) for s, t, _, _ in seen] == [(SYM, T0 + k * COLUMN_MS) for k in (1, 2, 3)]
    _, _, bids, asks = seen[-1]
    assert bids is not None and asks is not None
    assert (len(bids), next(iter(bids)), bids[10_000]) == (50, 10_000, 1.0)  # best first
    assert (next(iter(asks)), asks[10_001]) == (10_001, 2.0)
    assert w.liquid[-1][1].samples == 1  # the native column is built too


async def test_sampler_gets_the_instantaneous_book_never_the_average() -> None:
    """Rider 2: a level changed 10 ms before the deadline reads at its new size (a
    time-weighted column would read 0.1 x 9 + 0.9 x 1 = 1.8)."""
    w = World()
    eng = await live(w)
    seen = _recorder(w)
    w.topic.pin_native(SYM, 200)
    w.at(100)
    await eng.on_event(delta(11, 10, [lvl(10_000, 9)]))
    w.at(190)
    w.at(200)
    _, _, bids, _ = seen[-1]
    assert bids is not None and bids[10_000] == 9.0
    native = w.liquid[-1][1]  # the same deadline's averaged column, which the tracker never gets
    assert native.bid_sizes[10_000 - native.price_origin_ticks] == pytest.approx(1.8)


async def test_sampler_gets_none_while_the_book_resyncs() -> None:
    w = World()
    eng = await live(w)
    seen = _recorder(w)
    w.topic.pin_native(SYM, 200)
    w.at(100)
    await eng.on_event(delta(99, 50, [lvl(9_000, 1)]))  # a gap: the book leaves LIVE
    assert eng.phase is not BookPhase.LIVE
    w.at(110)
    w.at(200)
    w.at(300)
    assert [b is None for _, _, b, _ in seen] == [False, True, True]
    await eng.on_event(snap(400, *ladder()))
    w.at(410)
    w.at(500)
    assert seen[-1][2] is not None


async def test_late_deadline_is_handed_none() -> None:
    """Carry (d): a deadline closed more than one column late reads no levels."""
    w = World()
    await live(w)
    seen = _recorder(w)
    w.topic.pin_native(SYM, 200)
    w.at(100)
    w.at(350)  # 200 is closed late (350 >= 300); 300 is on time
    assert [(t - T0, b is None) for _, t, b, _ in seen] == [(100, False), (200, True), (300, False)]


async def test_leased_but_unpinned_symbol_is_not_sampled() -> None:
    w = World()
    await live(w)
    seen = _recorder(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    assert seen == []


async def test_sampler_fault_is_contained() -> None:
    w = World()
    await live(w)

    def boom(symbol: str, t_ms: int, levels: NativeLevels | None) -> None:
        raise RuntimeError("tracker fault")

    w.topic.set_sampler(boom)
    w.topic.pin_native(SYM, 200)
    w.at(100)
    w.at(200)
    assert len(w.liquid) == 2  # the native columns go on


async def test_unpin_without_a_lease_drops_the_symbol() -> None:
    w = World()
    await live(w)
    w.topic.pin_native(SYM, 200)
    w.at(100)
    assert SYM in w.topic._symbols and w.topic.pinned == {SYM}
    w.topic.unpin_native(SYM)
    assert SYM not in w.topic._symbols and w.topic.pinned == frozenset()
    w.topic.unpin_native(SYM)  # idempotent


async def test_pin_outlives_a_lease_and_the_lease_outlives_a_pin() -> None:
    w = World()
    await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    w.topic.pin_native(SYM, 200)
    sub = w.hold(spec)
    assert sub.heatmap_lease is not None
    w.topic.release(sub.heatmap_lease)
    assert SYM in w.topic._symbols  # `_free` keeps a pinned symbol
    sub = w.hold(spec)
    w.topic.unpin_native(SYM)
    assert SYM in w.topic._symbols  # the lease still holds it
    assert sub.heatmap_lease is not None
    w.topic.release(sub.heatmap_lease)
    assert SYM not in w.topic._symbols


async def test_pin_reads_at_least_its_depth() -> None:
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, depth=50, time_bucket_ms=100))
    st = w.topic._symbols[SYM]
    assert st.native.spec.depth == 50
    w.topic.pin_native(SYM, 200)
    assert st.native.spec.depth == 200
    w.topic.unpin_native(SYM)
    assert st.native.spec.depth == 50


async def test_pins_are_capped_and_counted() -> None:
    w = World()
    topic = w.topic
    topic._max_pinned = 2
    topic.pin_native("BTCUSDT", 200)
    topic.pin_native("ETHUSDT", 200)
    topic.pin_native("ETHUSDT", 200)  # a repeat is no new pin
    assert _pinned_gauge() == 2
    with pytest.raises(ValueError, match="At most 2"):
        topic.pin_native("SOLUSDT", 200)
    topic.unpin_native("ETHUSDT")
    assert _pinned_gauge() == 1
    topic.unpin_native("BTCUSDT")
    assert _pinned_gauge() == 0


@pytest.mark.parametrize("depth", [0, DEEP_DEPTH])
def test_pin_depth_stays_below_the_deep_tier(depth: int) -> None:
    w = World()
    with pytest.raises(ValueError, match="deep tier"):
        w.topic.pin_native(SYM, depth)
    assert w.topic.pinned == frozenset()


# -- a pin holds the book demand itself (fold 1) ---------------------------------------------------


async def test_a_pin_demands_the_book_at_its_depth_and_unpin_releases_it() -> None:
    w = World()
    demand = w.topic._demand = Demand()
    w.topic.pin_native(SYM, 200)
    w.topic.pin_native(SYM, 200)  # a repeat asks again, under the same consumer (idempotent)
    assert demand.calls == [("acquire", H.PIN_CONSUMER, SYM, "200")] * 2
    w.topic.unpin_native(SYM)
    w.topic.unpin_native(SYM)  # nothing left to release
    assert demand.calls[2:] == [("release", H.PIN_CONSUMER, SYM)]


async def test_a_pin_demand_is_its_own_reference_beside_a_deep_spec() -> None:
    w = World()
    demand = w.topic._demand = Demand()
    w.topic.pin_native(SYM, 200)
    sub = w.hold(HeatmapSpec(SYM, depth=500, time_bucket_ms=100))
    assert sub.heatmap_lease is not None
    w.topic.release(sub.heatmap_lease)
    assert demand.calls == [
        ("acquire", H.PIN_CONSUMER, SYM, "200"),
        ("acquire", H.DEEP_CONSUMER, SYM, "500"),
        ("release", H.DEEP_CONSUMER, SYM),
    ]  # the deep spec's release leaves the pin's demand held


async def test_stop_releases_every_pin_demand() -> None:
    w = World()
    demand = w.topic._demand = Demand()
    w.topic.pin_native(SYM, 200)
    w.topic.pin_native("ETHUSDT", 100)
    await w.topic.stop()
    assert sorted(c for c in demand.calls if c[0] == "release") == [
        ("release", H.PIN_CONSUMER, "BTCUSDT"), ("release", H.PIN_CONSUMER, "ETHUSDT"),
    ]  # fmt: skip
    assert w.topic.pinned == frozenset() and _pinned_gauge() == 0


class _Refusing(Demand):
    def __init__(self) -> None:
        super().__init__()
        self.listed = False

    def acquire_depth(self, consumer: str, symbol: str, depth: int) -> None:
        super().acquire_depth(consumer, symbol, depth)
        if not self.listed:
            raise LookupError(symbol)  # `BookStream`: `UnknownSymbolError`


async def test_a_refused_pin_demand_is_inert_and_asked_again_on_the_retry_cadence() -> None:
    w = World()
    demand = w.topic._demand = _Refusing()
    w.topic.pin_native(SYM, 200)  # logged, never raised: the pin is held, inert
    assert w.topic.pinned == {SYM} and len(demand.calls) == 1
    w.at(100)  # the first retry is due at once
    assert len(demand.calls) == 2
    w.at(H.PIN_RETRY_MS - 100)
    assert len(demand.calls) == 2  # not before the cadence
    demand.listed = True
    w.at(H.PIN_RETRY_MS + 200)
    assert len(demand.calls) == 3 and SYM not in w.topic._pin_owed
    w.at(3 * H.PIN_RETRY_MS)
    assert len(demand.calls) == 3  # held: never asked again


async def test_unpin_of_a_refused_pin_releases_nothing() -> None:
    w = World()
    demand = w.topic._demand = _Refusing()
    w.topic.pin_native(SYM, 200)
    w.topic.unpin_native(SYM)
    assert [c[0] for c in demand.calls] == ["acquire"] and w.topic._pin_owed == set()


# -- a native depth change reads the book at the new depth (fold 5) --------------------------------


async def test_a_native_depth_change_never_leaves_the_next_sample_without_levels() -> None:
    """Pin 100 and a 200 lease: the native column reads 200. Its release takes the native depth
    back to 100, which nothing had read; the book is read then, so the next deadline samples it
    instead of reading a spurious gap."""
    w = World()
    await live(w)
    seen = _recorder(w)
    w.topic.pin_native(SYM, 100)
    sub = w.hold(HeatmapSpec(SYM, depth=200, time_bucket_ms=100))
    st = w.topic._symbols[SYM]
    assert st.native.spec.depth == 200
    st.levels.pop(100, None)  # only the 200 levels are held, as after a turn at depth 200
    assert sub.heatmap_lease is not None
    w.topic.release(sub.heatmap_lease)
    assert st.native.spec.depth == 100 and 100 in st.levels
    w.at(100)
    assert seen[-1][2] is not None
