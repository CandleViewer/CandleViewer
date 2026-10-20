"""Scenario 5, "A bar is amended late" (E13-T02, #426; 24-internal-schemas §7.4; 23 §6.1, §8.2):
a late trade re-closes a closed time bar with `amended=True`; each instance replays from its newest
checkpoint at or before that bar, republishes every point that changed with `amended: true`, and
ends equal, bit for bit, to a from-scratch fold of the corrected series."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.indicators.engine import IndicatorEngine, Point, Requested
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.metrics import RECOMPUTES
from candleviewer.orderflow.indicators.types import KernelContext, bar_input
from tests.unit.orderflow.indicators._engine import (
    M1,
    S1,
    SYM,
    Listener,
    admit,
    bar,
    close,
    counter,
    wave,
)

#: One instance of every server indicator, at parameters short enough to be defined early.
EVERY: list[dict[str, Any]] = [
    {"indicator": "sma", "params": {"n": 5}},
    {"indicator": "ema", "params": {"n": 4}},
    {"indicator": "rsi", "params": {"n": 6}},
    {"indicator": "atr", "params": {"n": 5}},
    {"indicator": "adx", "params": {"n": 4}},
    {"indicator": "vwap"},
    {"indicator": "cvd"},
    {"indicator": "volume"},
    {"indicator": "zigzag", "params": {"depth": 2}},
]


def _from_scratch(store: SeriesStore, spec: BarSpec, r: Requested) -> list[tuple[str, ...]]:
    """The fold of the series the store now holds, by the same kernel, as reprs."""
    latest = store.latest(SYM, spec.spec_hash, 1001)
    assert latest is not None
    rows = compute(
        r.definition.id, [bar_input(b) for b in latest.closed], r.params,
        source=r.kernel.sources[0], context=KernelContext(),
    )  # fmt: skip
    return [tuple(repr(v) for v in row) for row in rows]


def _values(points: tuple[Point, ...]) -> list[tuple[str, ...]]:
    return [tuple(repr(v) for v in p.values) for p in points]


@pytest.mark.parametrize("instance", EVERY, ids=[i["indicator"] for i in EVERY])
async def test_amended_close_recomputes_forward_and_republishes(instance: dict[str, Any]) -> None:
    store, listener = SeriesStore(), Listener()
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    (r,) = admit(engine, [instance], spec=S1)
    for k in range(40):
        await close(store, engine, wave(k, spec=S1, volume=1.0 + k % 3, delta=k % 5 - 2.0), spec=S1)
    before = engine.snapshot(SYM, r.key, 500)
    assert before is not None
    listener.events.clear()
    amended_runs = counter(RECOMPUTES["amended"])
    late = bar(33, 140.0, spec=S1, high=141.0, low=99.0, volume=9.0, delta=-7.0)
    await close(store, engine, late, spec=S1, amended=True)  # a late trade re-closes bar 33
    after = engine.snapshot(SYM, r.key, 500)
    assert after is not None
    assert _values(after.points) == _from_scratch(store, S1, r)
    assert [p.index for p in after.points] == list(range(40))
    changed = {p.index for p, q in zip(after.points, before.points, strict=True) if p != q}
    assert changed and min(changed) >= 33  # nothing before the amended bar moves
    ((kind, batches),) = listener.events
    published = batches[r.key].points
    assert kind == "points" and {p.index for p in published} == changed
    assert all(p.amended for p in published)
    assert [p for p in after.points if p.index in changed] == list(published)
    assert counter(RECOMPUTES["amended"]) - amended_runs == 1
    hold.release()


async def test_a_repeated_close_that_changes_nothing_publishes_nothing() -> None:
    store, listener = SeriesStore(), Listener()
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    admit(engine, EVERY[:2], spec=S1)
    bars = [wave(k, spec=S1) for k in range(12)]
    for b in bars:
        await close(store, engine, b, spec=S1)
    listener.events.clear()
    await close(store, engine, bars[9], spec=S1, amended=True)
    assert listener.events == []
    hold.release()


async def test_an_amendment_older_than_the_ring_re_primes_and_re_snapshots() -> None:
    """A 1m series keeps 11 bars (the 60 s window reaches 3, plus the checkpoint spacing): bar 5
    of 30 is out of it, so its instances re-prime from the store (`backfill`) and the listener
    re-snapshots them (`history_repair`)."""
    store, listener = SeriesStore(), Listener()
    hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    (r,) = admit(engine, EVERY[1:2])
    for k in range(30):
        await close(store, engine, wave(k))
    listener.events.clear()
    backfills = counter(RECOMPUTES["backfill"])
    await close(store, engine, bar(5, 150.0), amended=True)
    assert listener.events == [("resnapshot", "history_repair")]
    assert counter(RECOMPUTES["backfill"]) - backfills == 1
    after = engine.snapshot(SYM, r.key, 500)
    assert after is not None and _values(after.points) == _from_scratch(store, M1, r)
    hold.release()


async def test_amendments_across_a_gap_regenerate_its_fillers() -> None:
    """A time series is densified (24 §7.4): the fillers after an amended bar are flat at its new
    close, so the replay rebuilds them and the values after the gap move with it."""
    store = SeriesStore()
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    (r,) = admit(engine, [{"indicator": "sma", "params": {"n": 4}}], spec=S1)
    slots = [0, 1, 2, 3, 4, 8, 9, 10]  # an empty run of three slots after bar 4
    for i, slot in enumerate(slots):
        await close(store, engine, bar(i, 100.0 + i, spec=S1, slot=slot), spec=S1)
    await close(store, engine, bar(4, 90.0, spec=S1, slot=4), spec=S1, amended=True)
    after = engine.snapshot(SYM, r.key, 500)
    assert after is not None
    # SMA(4) of the densified closes: bar 5 averages the three fillers (90) and itself (105).
    assert after.points[5].values == ((90.0 + 90.0 + 90.0 + 105.0) / 4,)
    hold.release()


async def test_an_amendment_before_the_rings_first_checkpoint_re_primes() -> None:
    """The ring's oldest bars can precede its first checkpoint (one every 8): an amendment there,
    older than the builder's window anyway, re-primes rather than replay from nothing."""
    store, listener = SeriesStore(), Listener()
    hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    (r,) = admit(engine, EVERY[1:2])
    for k in range(30):  # the 11-bar ring holds bars 19..29, checkpointed at bar 24
        await close(store, engine, wave(k))
    listener.events.clear()
    await close(store, engine, bar(20, 150.0), amended=True)
    assert listener.events == [("resnapshot", "history_repair")]
    after = engine.snapshot(SYM, r.key, 500)
    assert after is not None and _values(after.points) == _from_scratch(store, M1, r)
    hold.release()


async def test_a_replay_across_a_gap_past_the_fill_bound_restarts_as_the_live_fold_did() -> None:
    store = SeriesStore()
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    (r,) = admit(engine, [{"indicator": "ema", "params": {"n": 2}}], spec=S1)
    slots = [*range(10), 2_000, 2_001]  # 1 990 empty slots before bar 10
    for i, slot in enumerate(slots):
        await close(store, engine, bar(i, 100.0 + i, spec=S1, slot=slot), spec=S1)
    before = engine.snapshot(SYM, r.key, 500)
    await close(store, engine, bar(9, 50.0, spec=S1, slot=9), spec=S1, amended=True)
    after = engine.snapshot(SYM, r.key, 500)
    assert before is not None and after is not None
    changed = [p.index for p, q in zip(after.points, before.points, strict=True) if p != q]
    assert changed == [9]  # after the restart, bars 10 and 11 fold as before
    assert after.points[10].values == (None,)  # the restart's warmup, as live
    hold.release()
