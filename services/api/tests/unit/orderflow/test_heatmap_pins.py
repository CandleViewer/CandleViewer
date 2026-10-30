"""E21-T04 PR 2 (#710): `HeatmapTopic.pin_native` and the native sampler, the liquidity tracker's
one book sampler (carry e): a pinned symbol's native column is built without a lease, each native
deadline hands the sampler the instantaneous levels (never an averaged column), a resync or a late
deadline hands it None, and an un-pinned, unleased symbol is dropped as `_free` drops it. Fake
epoch-ms clock, synthetic levels; no network."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from candleviewer.book.models import BookPhase
from candleviewer.orderflow.heatmap import COLUMN_MS, DEEP_DEPTH, HeatmapSpec, NativeLevels
from tests.unit.book._builders import delta, lvl, snap
from tests.unit.orderflow.test_heatmap import SYM, T0, World, ladder, live

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
