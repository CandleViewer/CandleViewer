"""The indicator engine's priming, full recomputes, densified time series, generation swaps and
store repairs (E13-T02, #426; 24-internal-schemas §3.3, §7.4; 23 §6.1, §7.4; SR-E13-04)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import structlog

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarKey, BarPage, BarReader, BarTail
from candleviewer.bars.rows import bar_row, row_checksum
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.errors import RecomputeRefusedError
from candleviewer.orderflow.indicators.engine import (
    MAX_FILL_SLOTS,
    IndicatorEngine,
    Requested,
    stored_history,
)
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.metrics import CAP_REJECTED, RECOMPUTES
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Unavailable, bar_input
from tests.unit.orderflow.indicators._engine import (
    EMA3,
    M1,
    SYM,
    T5,
    Listener,
    admit,
    close,
    counter,
    wave,
)

GEN = 3
SMA20 = [{"indicator": "sma", "params": {"n": 20}}]


def _reprs(rows: list[Any]) -> list[tuple[str, ...]]:
    return [tuple(repr(v) for v in row) for row in rows]


def _fold(r: Requested, bars: list[BarInput]) -> list[tuple[str, ...]]:
    ctx = KernelContext()
    rows = compute(r.definition.id, bars, r.params, source=r.kernel.sources[0], context=ctx)
    return _reprs(rows)


class _Tail:
    """The store's hydration read: bars 100..109 of generation `GEN` (the newest ten)."""

    def __init__(self) -> None:
        self.bars = [wave(i) for i in range(100, 110)]

    async def __call__(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(GEN, b) for b in self.bars], since_us=0, fetched=len(self.bars))


class _History:
    """`HistoryRead`: bars 85..109 of `GEN` (a read overlaps the store; the engine keeps only the
    older ones), released by `go`; raises `fail` when set."""

    def __init__(self) -> None:
        self.go = asyncio.Event()
        self.go.set()
        self.fail: Exception | None = None
        self.calls: list[tuple[str, int, int, int]] = []

    async def __call__(
        self, symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        self.calls.append((symbol, generation, start_us, end_us))
        await self.go.wait()
        if self.fail is not None:
            raise self.fail
        return [(i, bar_input(wave(i))) for i in range(85, 110)]


async def _hydrated(history: _History, **kw: Any) -> tuple[SeriesStore, IndicatorEngine, Any]:
    store = SeriesStore(_Tail())
    hold = await store.ensure(SYM, M1)
    return store, IndicatorEngine(store, history=history, **kw), hold


async def _done(engine: IndicatorEngine) -> None:
    await asyncio.gather(*list(engine._tasks))


async def test_a_new_instance_primes_from_the_store_when_its_bars_suffice() -> None:
    history = _History()
    store, engine, _hold = await _hydrated(history)
    (r,) = admit(engine, EMA3, history=5)  # 3 + 5 bars: the store's 10 suffice
    batch, latest = engine.snapshot(SYM, r.key, 500), store.latest(SYM, M1.spec_hash, 11)
    assert batch is not None and latest is not None and history.calls == []
    assert [p.index for p in batch.points] == list(range(100, 110))
    assert {p.generation for p in batch.points} == {GEN}
    expected = _fold(r, [bar_input(b) for b in latest.closed])
    assert _reprs([p.values for p in batch.points]) == expected


async def test_older_bars_are_read_on_a_slot_and_the_instance_waits_until_primed() -> None:
    """SMA(20) with history 5 needs 25 bars; the store holds 10 from index 100, so the older
    ones exist: one read of the 25 slots ending at the newest bar, in a task the engine owns.
    The instance is not ready meanwhile, and `ready` tells the listener when it is."""
    history, listener = _History(), Listener()
    history.go.clear()
    _store, engine, _hold = await _hydrated(history)
    engine.listen(listener)
    (r,) = admit(engine, SMA20, history=5)
    await asyncio.sleep(0)  # one turn of the loop: the engine's task starts its read
    assert engine.snapshot(SYM, r.key, 5) is None
    assert engine.read(SYM, r.key) == Unavailable("missing")
    newest = wave(109).open_time
    assert history.calls == [(SYM, GEN, newest - 24 * 60_000_000, newest + 1)]
    history.go.set()
    await _done(engine)
    assert listener.events == [("ready", M1.spec_hash)]
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None and [p.index for p in batch.points] == list(range(85, 110))
    expected = _fold(r, [bar_input(wave(i)) for i in range(85, 110)])
    assert _reprs([p.values for p in batch.points]) == expected
    assert engine._busy == 0


async def test_a_read_with_no_free_slot_is_refused_never_queued() -> None:
    history = _History()
    history.go.clear()
    _store, engine, _hold = await _hydrated(history, slots=1)
    admit(engine, SMA20, history=5)  # takes the one slot, and waits there
    await asyncio.sleep(0)  # one turn of the loop: the read starts
    refused = counter(CAP_REJECTED["recompute"])
    with pytest.raises(RecomputeRefusedError) as caught:
        admit(engine, [{"indicator": "sma", "params": {"n": 21}}], consumer="c2", history=5)
    assert caught.value.cap == "recompute"
    assert counter(CAP_REJECTED["recompute"]) - refused == 1
    assert engine.instances(SYM, M1.spec_hash) == 1 and len(history.calls) == 1  # nothing held
    admit(engine, EMA3, consumer="c3", history=5)  # no read needed: admitted at once
    history.go.set()
    await _done(engine)


async def test_a_failed_read_primes_from_the_store_alone_and_logs() -> None:
    history = _History()
    history.fail = OSError("down")
    _store, engine, _hold = await _hydrated(history)
    with structlog.testing.capture_logs() as logs:
        (r,) = admit(engine, SMA20, history=5)
        await _done(engine)
    assert [(e["event"], e["error_type"]) for e in logs] == [
        ("indicator_backfill_failed", "OSError")
    ]
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None and [p.index for p in batch.points] == list(range(100, 110))
    assert engine._busy == 0


async def test_stop_cancels_a_running_read_and_refuses_new_ones() -> None:
    history = _History()
    history.go.clear()
    _store, engine, _hold = await _hydrated(history)
    admit(engine, SMA20, history=5)
    await asyncio.sleep(0)  # let the read start waiting
    await engine.stop()
    assert engine._tasks == set() and engine._busy == 0
    with pytest.raises(RecomputeRefusedError):
        admit(engine, [{"indicator": "sma", "params": {"n": 30}}], consumer="c2", history=5)


async def test_stored_history_reads_one_generations_closed_tape_bars_oldest_first() -> None:
    """The `HistoryRead` over a real `BarReader` (parameterised SQL): tape rows of the generation,
    closed, with an index; another generation's, a kline row (no index) and an open one are
    left out, though each passes the reader's integrity check."""

    def row(i: int, generation: int = GEN, **change: object) -> dict[str, object]:
        out = {**bar_row(wave(i), M1, generation=generation), **change}
        out["row_checksum"] = row_checksum(out)
        return out

    rows = [
        row(5),
        row(6),
        row(7, GEN + 1),
        row(8, source="kline", index=None),
        row(9, is_closed=False),
    ]
    queries: list[tuple[object, ...]] = []

    class _Fetch:
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            queries.append(params)
            return rows

    read = stored_history(BarReader(_Fetch(), _no_rebuild))
    got = await read(SYM, M1, GEN, wave(0).open_time, wave(10).open_time)
    assert list(got) == [(i, bar_input(wave(i))) for i in (5, 6)]
    assert len(queries) == 1 and queries[0][0] == SYM  # a bind, never inlined


async def _no_rebuild(symbol: str, spec_hash: str, from_us: int, to_us: int) -> None:
    return None


async def test_a_time_series_is_densified_as_bar_series_densify_does() -> None:
    store = SeriesStore()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    sma, vwap = admit(engine, [{"indicator": "sma", "params": {"n": 2}}, {"indicator": "vwap"}])
    slots = [0, 1, 2, 5, 6, 9]
    bars: list[Bar] = [wave(i, slot=s) for i, s in enumerate(slots)]
    for b in bars:
        await close(store, engine, b)
    dense = BarSeries(M1, bars).densify()
    real = [k for k, b in enumerate(dense) if not b.synthetic]
    for r in (sma, vwap):
        expected = _fold(r, [bar_input(b) for b in dense])
        batch = engine.snapshot(SYM, r.key, 500)
        assert batch is not None and [p.index for p in batch.points] == list(range(6))
        assert _reprs([p.values for p in batch.points]) == [expected[k] for k in real]


async def test_a_gap_past_the_fill_bound_restarts_the_kernel() -> None:
    store = SeriesStore()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    (r,) = admit(engine, EMA3)
    for i in range(4):
        await close(store, engine, wave(i))
    assert engine.read(SYM, r.key) != Unavailable("warmup")
    await close(store, engine, wave(4, slot=3 + MAX_FILL_SLOTS + 2))  # 1 001 empty slots
    assert engine.read(SYM, r.key) == Unavailable("warmup")  # a new warmup follows
    batch = engine.snapshot(SYM, r.key, 2)
    assert batch is not None and batch.points[-1].values == (None,)


async def test_a_generation_swap_re_primes_every_instance_and_re_snapshots() -> None:
    store, listener = SeriesStore(), Listener()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    a, b = admit(engine, [*EMA3, {"indicator": "cvd"}])
    for i in range(6):
        await close(store, engine, wave(i), generation=0)
    backfills = counter(RECOMPUTES["backfill"])
    listener.events.clear()
    await close(store, engine, wave(0, slot=6), generation=1)  # a cold start: index 0 again
    assert listener.events == [("resnapshot", "generation_swap")]
    assert counter(RECOMPUTES["backfill"]) - backfills == 2
    for r in (a, b):
        batch = engine.snapshot(SYM, r.key, 500)
        assert batch is not None and [(p.generation, p.index) for p in batch.points] == [(1, 0)]


async def test_a_store_repair_re_primes_the_series_and_re_snapshots_it() -> None:
    store, listener = SeriesStore(), Listener()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    admit(engine, EMA3)
    await close(store, engine, wave(0))
    listener.events.clear()
    engine.history_repair(SYM, M1, 1)
    engine.history_repair(SYM, BarSpec(kind="time", interval_ms=300_000), 1)  # nobody reads it
    assert listener.events == [("resnapshot", "history_repair")]


async def test_a_non_time_series_is_never_densified_and_a_re_close_re_primes() -> None:
    store, listener = SeriesStore(), Listener()
    _hold = await store.ensure(SYM, T5)
    engine = IndicatorEngine(store)
    engine.listen(listener)
    (r,) = admit(engine, [{"indicator": "sma", "params": {"n": 2}}], spec=T5)
    for i, slot in enumerate((0, 7, 8)):  # open times far apart: tick bars have no slots
        await close(store, engine, wave(i, spec=T5, slot=slot), spec=T5)
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None
    inputs = [bar_input(wave(i, spec=T5, slot=s)) for i, s in enumerate((0, 7, 8))]
    assert _reprs([p.values for p in batch.points]) == _fold(r, inputs)  # no fillers
    listener.events.clear()
    await close(store, engine, wave(2, spec=T5, slot=8), spec=T5)  # bar 2 closed again
    assert listener.events == [("resnapshot", "history_repair")]  # no ring: it re-primes


async def test_stored_history_pages_through_the_window_and_stops_at_its_bound() -> None:
    """A read past one page follows the reader's cursor; `max_rows` bounds the rows taken."""

    class _Pages:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int | None]] = []

        async def read_bars(
            self, symbol: str, spec: BarSpec, from_us: int, to_us: int, limit: int, *,
            after_us: int | None = None, at_key: BarKey | None = None,
        ) -> BarPage:  # fmt: skip
            self.calls.append((limit, after_us))
            first = 0 if after_us is None else 2
            rows = [bar_row(wave(i), M1, generation=GEN) for i in range(first, first + 2)]
            return BarPage(rows, wave(first + 1).open_time if first == 0 else None, stale=False)

    pages = _Pages()
    read = stored_history(pages, max_rows=10)
    got = await read(SYM, M1, GEN, wave(0).open_time, wave(9).open_time)
    assert [i for i, _ in got] == [0, 1, 2, 3]
    assert pages.calls == [(10, None), (8, wave(1).open_time)]


async def test_a_series_re_primes_through_a_read_when_its_instances_need_one() -> None:
    history, listener = _History(), Listener()
    _store, engine, _hold = await _hydrated(history)
    engine.listen(listener)
    (r,) = admit(engine, SMA20, history=5)
    await _done(engine)
    listener.events.clear()
    history.go.clear()
    engine.history_repair(SYM, M1, 1)  # SMA(20) needs older bars again: a read, then ready
    assert engine.snapshot(SYM, r.key, 5) is None
    history.go.set()
    await _done(engine)
    assert listener.events == [("resnapshot", "history_repair"), ("ready", M1.spec_hash)]
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None and [p.index for p in batch.points] == list(range(85, 110))


async def test_an_instance_gone_before_its_read_ends_is_not_primed_and_a_crash_is_logged() -> None:
    now = [0]
    history = _History()
    history.go.clear()
    _store, engine, _hold = await _hydrated(history, now_us=lambda: now[0])
    (r,) = admit(engine, SMA20, history=5)
    await asyncio.sleep(0)  # the read starts and waits
    engine.release(SYM, [r.key], "c1")
    now[0] = 30_000_000  # past its grace: the next sweep removes it
    engine.release(SYM, [], "nobody")
    history.go.set()
    await _done(engine)
    assert engine.snapshot(SYM, r.key, 5) is None and engine.instances(SYM, M1.spec_hash) == 0

    class _Broken(Listener):
        def ready(self, symbol: str, spec: BarSpec) -> None:
            raise RuntimeError("listener")

    engine.listen(_Broken())
    with structlog.testing.capture_logs() as logs:
        admit(engine, SMA20, history=5, consumer="c2")
        await asyncio.gather(*list(engine._tasks), return_exceptions=True)
        await asyncio.sleep(0)  # the done callback runs on the next turn
    assert [(e["event"], e["error_type"]) for e in logs] == [
        ("indicator_backfill_crashed", "RuntimeError")
    ]
    assert engine._busy == 0
