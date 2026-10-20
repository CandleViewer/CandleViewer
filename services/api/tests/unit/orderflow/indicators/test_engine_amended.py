"""Scenario 5, "A bar is amended late" (E13-T02, #426; 24-internal-schemas §7.4; 23 §6.1, §8.2):
a late trade re-closes a closed time bar with `amended=True`; each instance replays from its newest
checkpoint at or before that bar, republishes every point that changed with `amended: true`, and
ends equal, bit for bit, to a from-scratch fold of the corrected series. C-2.17 bounds the replays,
in each instance and in the series' instances together, checkpoints weighed by size; past either
bound the series re-primes and re-snapshots instead."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import Hold, SeriesStore
from candleviewer.orderflow.indicators.engine import IndicatorEngine, Point, Requested
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.limits import (
    CHECKPOINT_EVERY,
    MAX_AMEND_SERIES_UPDATES,
    MAX_AMEND_UPDATES,
    MAX_FILL_SLOTS,
)
from candleviewer.orderflow.indicators.metrics import RECOMPUTES
from candleviewer.orderflow.indicators.types import KernelContext, bar_input
from tests.unit.orderflow.indicators._engine import (
    M1,
    S1,
    SYM,
    Listener,
    Primed,
    admit,
    bar,
    close,
    counter,
    late,
    primed,
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


def _densified(store: SeriesStore, spec: BarSpec, r: Requested) -> list[tuple[str, ...]]:
    """`_from_scratch` of the densified series (its fillers folded too), at its real bars."""
    latest = store.latest(SYM, spec.spec_hash, 1001)
    assert latest is not None
    dense = BarSeries(spec, list(latest.closed)).densify()
    inputs = [bar_input(b) for b in dense]
    rows = compute(r.definition.id, inputs, r.params, source=r.kernel.sources[0])
    return [
        tuple(repr(v) for v in row) for row, b in zip(rows, dense, strict=True) if not b.synthetic
    ]


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


async def test_a_replay_re_takes_each_checkpoint_after_the_amended_bar() -> None:
    """A replay refreshes the checkpoints after the amended bar: their state and the real bar
    before them, which the next replay regenerates fillers from (and its bound reads). Bar 16
    opens after three empty slots, so a second amendment, replaying from the checkpoint before
    bar 16, folds fillers flat at bar 15's corrected close, and EMA(3) carries it on."""
    store = SeriesStore()
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    (r,) = admit(engine, [{"indicator": "ema", "params": {"n": 3}}], spec=S1)
    slots = [*range(16), 19, 20, 21, 22]  # checkpoints before bars 0, 8 and 16
    for k, slot in enumerate(slots):
        await close(store, engine, wave(k, spec=S1, slot=slot), spec=S1)
    for index in (15, 17):
        b = wave(index, spec=S1, slot=slots[index])
        await close(
            store, engine, b.model_copy(update={"close": b.close + 5}), spec=S1, amended=True
        )
    after = engine.snapshot(SYM, r.key, 500)
    assert after is not None and _values(after.points) == _densified(store, S1, r)
    hold.release()


@dataclass(frozen=True)
class _Gap:
    store: SeriesStore
    hold: Hold
    engine: IndicatorEngine
    listener: Listener
    requested: tuple[Requested, ...]
    late: Bar


async def _after_a_long_gap(instances: list[dict[str, Any]], *, over: int = 0) -> _Gap:
    """`instances` (a system consumer's: no user cap) on a one-second series: bars 0..7 a second
    apart, then `MAX_FILL_SLOTS` empty slots, then bars 8..15, with `over` more empty slots before
    bar 12. Bar 8 is a checkpoint after the gap, so `late`, a re-close of bar 15 with another
    close, replays bar 8's fillers and the eight bars from it: `MAX_AMEND_UPDATES` kernel updates
    in each instance, plus `over`."""
    assert MAX_FILL_SLOTS + CHECKPOINT_EVERY == MAX_AMEND_UPDATES  # the replay this builds
    store, listener = SeriesStore(), Listener()
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    requested = admit(engine, instances, spec=S1, user=None)
    after_gap = 7 + MAX_FILL_SLOTS + 1  # bar 8: every empty slot before it is a filler
    slots = [*range(8), *(after_gap + k + (over if k >= 4 else 0) for k in range(8))]
    for i, slot in enumerate(slots):
        await close(store, engine, bar(i, 100.0 + i % 3, spec=S1, slot=slot), spec=S1)
    listener.events.clear()
    late = bar(15, 90.0, spec=S1, slot=slots[15])
    return _Gap(store, hold, engine, listener, requested, late)


def _recomputes() -> tuple[float, float]:
    return counter(RECOMPUTES["amended"]), counter(RECOMPUTES["backfill"])


def _since(before: tuple[float, float]) -> list[float]:
    """The `amended` and `backfill` recomputes counted since `before` (`_recomputes`)."""
    return [a - b for a, b in zip(_recomputes(), before, strict=True)]


SMA4: list[dict[str, Any]] = [{"indicator": "sma", "params": {"n": 4}}]


async def test_a_replay_of_max_amend_updates_is_published_as_an_amended_point() -> None:
    """C-2.17 (security review of the WS delivery, round 4): an amended close replays the bars
    from its checkpoint on, their fillers included, within `MAX_AMEND_UPDATES` kernel updates. The
    re-close of bar 15 replays 1 008: one amended point is published, the replay is counted
    `amended`, and the instance ends as a from-scratch fold of the corrected series."""
    gap = await _after_a_long_gap(SMA4)
    (r,) = gap.requested
    before = _recomputes()
    await close(gap.store, gap.engine, gap.late, spec=S1, amended=True)
    ((kind, batches),) = gap.listener.events
    assert kind == "points" and [(p.index, p.amended) for p in batches[r.key].points] == [
        (15, True)
    ]
    assert _since(before) == [1, 0]
    after = gap.engine.snapshot(SYM, r.key, 500)
    assert after is not None and _values(after.points) == _densified(gap.store, S1, r)
    gap.hold.release()


async def test_a_replay_past_max_amend_updates_re_primes_the_series_instead() -> None:
    """C-2.17 (security review of the WS delivery, round 4): one more empty slot, before bar 12,
    makes the re-close of bar 15 a replay of 1 009 kernel updates, past `MAX_AMEND_UPDATES`: the
    series re-primes and re-snapshots instead (`history_repair`, counted `backfill`), and the
    instance ends as a from-scratch fold of the corrected series."""
    gap = await _after_a_long_gap(SMA4, over=1)
    (r,) = gap.requested
    before = _recomputes()
    await close(gap.store, gap.engine, gap.late, spec=S1, amended=True)
    assert gap.listener.events == [("resnapshot", "history_repair")]
    assert _since(before) == [0, 1]
    after = gap.engine.snapshot(SYM, r.key, 500)
    assert after is not None and _values(after.points) == _densified(gap.store, S1, r)
    gap.hold.release()


#: Distinct instances whose checkpoints hold a few hundred bytes (a restore weight of at most 13,
#: `RESTORE_BYTES_PER_UPDATE`): the SMA of 2 to 26 bars.
SMAS: list[dict[str, Any]] = [{"indicator": "sma", "params": {"n": n}} for n in range(2, 27)]


async def test_replays_within_the_series_budget_run_in_every_instance() -> None:
    """C-2.17 (security review of the WS delivery, round 5): an amended close's replays in the
    series' instances are added up before any runs (`MAX_AMEND_SERIES_UPDATES`). The re-close of
    bar 15 replays 1 008 kernel updates in each and restores a checkpoint of at most 316 bytes:
    24 instances take at most 24 576, within the budget, so each replays, publishes its amended
    point and is counted `amended`."""
    assert 24 * (MAX_AMEND_UPDATES + 16) <= MAX_AMEND_SERIES_UPDATES  # the replays this builds
    gap = await _after_a_long_gap(SMAS[:24])
    before = _recomputes()
    await close(gap.store, gap.engine, gap.late, spec=S1, amended=True)
    ((kind, batches),) = gap.listener.events
    assert kind == "points" and set(batches) == {r.key for r in gap.requested}
    assert all([(p.index, p.amended) for p in b.points] == [(15, True)] for b in batches.values())
    assert _since(before) == [24, 0]
    gap.hold.release()


async def test_replays_past_the_series_budget_re_prime_it_before_any_instance_replays() -> None:
    """C-2.17 (security review of the WS delivery, round 5): 25 such replays take at least 25 200
    kernel updates, past `MAX_AMEND_SERIES_UPDATES`, so no instance replays (none is counted
    `amended`): the series re-primes and re-snapshots (`history_repair`, counted `backfill` for
    each instance), here by a full recompute, as folding the store's bars for 25 instances takes
    more than `MAX_SYNC_PRIME_UPDATES`."""
    assert 25 * MAX_AMEND_UPDATES > MAX_AMEND_SERIES_UPDATES  # the replays this builds
    gap = await _after_a_long_gap(SMAS)
    before = _recomputes()
    await close(gap.store, gap.engine, gap.late, spec=S1, amended=True)
    await asyncio.gather(*list(gap.engine._tasks))
    assert gap.listener.events == [("resnapshot", "history_repair"), ("ready", S1.spec_hash)]
    assert _since(before) == [0, 25]
    gap.hold.release()


#: SMA instances of 4 977..5 000 bars: a full window makes each checkpoint about 31 KB, which a
#: restore takes about 1 ms to rebuild and weighs about 1 300 kernel updates
#: (`RESTORE_BYTES_PER_UPDATE`); re-taking one weighs about 160 (`SNAPSHOT_BYTES_PER_UPDATE`).
DEEP_SMAS: list[dict[str, Any]] = [
    {"indicator": "sma", "params": {"n": n}} for n in range(4_977, 5_001)
]


async def _replayed_or_re_primed(p: Primed, age: int) -> tuple[list[Any], list[float]]:
    """Re-close the bar `age` seconds before the newest (`late`) and let any re-prime end: what
    the listener heard, and the `amended` and `backfill` recomputes counted meanwhile."""
    listener = Listener()
    p.engine.listen(listener)
    before = _recomputes()
    await close(p.store, p.engine, late(p, age), spec=S1, amended=True)
    await asyncio.gather(*list(p.engine._tasks))
    p.hold.release()
    return listener.events, _since(before)


async def test_restoring_the_checkpoints_counts_toward_the_series_budget() -> None:
    """C-2.17 (security review of the WS delivery, round 5): a replay first restores its
    checkpoint, which counts toward `MAX_AMEND_SERIES_UPDATES` by size. Re-closing the newest bar
    replays eight bars in each of 24 deep SMA instances, 192 kernel updates, but their restores
    weigh about 31 000 more: the series re-primes (a full recompute) and no instance replays."""
    p = await primed(DEEP_SMAS, stored=5_500, live=4)
    events, recomputes = await _replayed_or_re_primed(p, 0)
    assert events == [("resnapshot", "history_repair"), ("ready", S1.spec_hash)]
    assert recomputes == [0, 24]


async def test_re_taking_the_checkpoints_after_the_bar_counts_toward_the_series_budget() -> None:
    """C-2.17 (security review of the WS delivery, round 5): a replay re-takes each checkpoint
    after the amended bar, which counts by size too. Re-closing the bar 60 s old replays 68 bars
    in each of 14 deep SMA instances: with their restores that weighs about 19 200 kernel
    updates, within the budget, but re-taking the eight checkpoints after it in each adds about
    18 300: the series re-primes (a full recompute) and no instance replays."""
    p = await primed(DEEP_SMAS[-14:], stored=5_500)
    events, recomputes = await _replayed_or_re_primed(p, 60)
    assert events == [("resnapshot", "history_repair"), ("ready", S1.spec_hash)]
    assert recomputes == [0, 14]
