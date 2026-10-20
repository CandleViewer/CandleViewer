"""The indicator engine's priming, full recomputes, densified time series, generation swaps and
store repairs (E13-T02, #426; 24-internal-schemas §3.3, §7.4; 23 §6.1, §7.4; SR-E13-04)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
import structlog

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarKey, BarPage, BarReader, BarTail
from candleviewer.bars.rows import bar_row, row_checksum
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.errors import HistoryIncompleteError, RecomputeRefusedError
from candleviewer.orderflow.indicators.engine import IndicatorEngine, Requested, StoredHistory
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.limits import MAX_FILL_SLOTS
from candleviewer.orderflow.indicators.metrics import CAP_REJECTED, RECOMPUTES
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Unavailable, bar_input
from tests.unit.orderflow.indicators._engine import (
    EMA3,
    M1,
    S1,
    SYM,
    T5,
    Listener,
    admit,
    close,
    counter,
    instances,
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
    assert instances(engine) == 1 and len(history.calls) == 1  # nothing held
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


class _Lossy(_History):
    """`_History` keeping only the bars `keep` passes, as a read that lost rows returns them."""

    def __init__(self, keep: Callable[[int], bool]) -> None:
        super().__init__()
        self.keep = keep

    async def __call__(
        self, symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        rows = await super().__call__(symbol, spec, generation, start_us, end_us)
        return [row for row in rows if self.keep(row[0])]


@pytest.mark.parametrize(
    "keep", [lambda i: i != 95, lambda i: i < 99], ids=["a-bar-inside", "the-bar-before-the-store"]
)
async def test_a_read_that_skips_an_index_primes_from_the_store_alone(
    keep: Callable[[int], bool],
) -> None:
    """Review of the WS delivery: a read whose bars skip an index (one lost inside it, or the
    last before the store's oldest) is incomplete. It is never folded with the hole as empty
    slots: the instance primes from the store alone, logged."""
    _store, engine, _hold = await _hydrated(_Lossy(keep))
    with structlog.testing.capture_logs() as logs:
        (r,) = admit(engine, SMA20, history=5)
        await _done(engine)
    assert [(e["event"], e["error_type"]) for e in logs] == [
        ("indicator_backfill_failed", "HistoryIncompleteError")
    ]
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None and [p.index for p in batch.points] == list(range(100, 110))


def _tail_of(bars: list[Bar]) -> Any:
    """The store's hydration read: `bars`, all of generation `GEN`."""

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(GEN, b) for b in bars[-limit:]], since_us=0, fetched=len(bars))

    return tail


#: A one-second series' 1 000 closes 100 s apart: folding them takes about 100 000 kernel updates.
SPARSE = [wave(i, spec=S1, slot=i * 100) for i in range(1_000)]


async def test_a_store_too_sparse_to_fold_at_once_needs_a_recompute_slot() -> None:
    """SR-E13-04 and C-2.17 (security review of the WS delivery): folding the sparse store takes
    more than `MAX_SYNC_PRIME_UPDATES`, so it is a full recompute even with no read: with no slot
    free the admission is refused (`recompute`), never queued, and holds nothing."""
    store = SeriesStore(_tail_of(SPARSE))
    _hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store, slots=0)
    refused = counter(CAP_REJECTED["recompute"])
    with pytest.raises(RecomputeRefusedError) as caught:
        admit(engine, EMA3, spec=S1, history=5)
    assert caught.value.cap == "recompute"
    assert counter(CAP_REJECTED["recompute"]) - refused == 1
    assert instances(engine, S1) == 0 and engine._leases._held == {}


async def test_a_sparse_store_is_folded_by_a_recompute_and_a_repair_keeps_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.17 (security review of the WS delivery): `admit` folds nothing of the sparse store at
    once; a full recompute folds the store's bars alone, a chunk at a time, while the instance is
    not ready. A store repair mid-fold then primes it at once, from the newest bars a fold of
    `MAX_SYNC_PRIME_UPDATES` kernel updates reaches (80 bars 100 s apart), never the whole store."""
    store = SeriesStore(_tail_of(SPARSE))
    _hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    folding = _Folding(engine, monkeypatch)
    (r,) = admit(engine, EMA3, spec=S1, history=5)
    assert engine.snapshot(SYM, r.key, 5) is None and engine._busy == 1

    async def repair() -> None:
        await folding.begun(engine, r)
        engine.history_repair(SYM, S1, 1)

    await asyncio.gather(repair(), _done(engine))
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and [p.index for p in batch.points] == list(range(920, 1_000))


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


def _row(i: int, generation: int = GEN, **change: object) -> dict[str, object]:
    """Bar `i` of `generation` as a stored row, its checksum recomputed after `change`."""
    out = {**bar_row(wave(i), M1, generation=generation), **change}
    out["row_checksum"] = row_checksum(out)
    return out


class _Rows:
    """A PG-wire fake for `BarReader.read_bars` that returns `rows` to every query it records."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.queries: list[tuple[object, ...]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.queries.append(params)
        return self.rows


async def test_stored_history_reads_one_generations_closed_tape_bars_oldest_first() -> None:
    """The `HistoryRead` over a real `BarReader` (parameterised SQL): tape rows of the generation,
    closed, with an index; another generation's and a kline row (no index) are left out, though
    each passes the reader's integrity check."""
    rows = _Rows([_row(5), _row(6), _row(7, GEN + 1), _row(8, source="kline", index=None)])
    read = StoredHistory(BarReader(rows, _no_rebuild))
    got = await read(SYM, M1, GEN, wave(0).open_time, wave(10).open_time)
    assert list(got) == [(i, bar_input(wave(i))) for i in (5, 6)]
    assert len(rows.queries) == 1 and rows.queries[0][0] == SYM  # a bind, never inlined


@pytest.mark.parametrize(
    "bad",
    [_row(6, is_closed=False), _row(6, index=None), {**_row(6), "row_checksum": "0" * 64}],
    ids=["open", "no-index", "withheld"],
)
async def test_stored_history_fails_when_a_bar_of_the_generation_is_missing(
    bad: dict[str, object],
) -> None:
    """Review of the WS delivery: a bar of the generation the read cannot fold (still open, or
    with no index) and a page whose integrity check withheld a row (`integrity_degraded`,
    SR-E12-11) make the read incomplete, a failure: never a hole folded as empty slots."""
    read = StoredHistory(BarReader(_Rows([_row(5), bad, _row(7)]), _no_rebuild))
    with pytest.raises(HistoryIncompleteError):
        await read(SYM, M1, GEN, wave(0).open_time, wave(10).open_time)


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
    read = StoredHistory(pages, max_rows=10)
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
    assert engine.snapshot(SYM, r.key, 5) is None and instances(engine) == 0

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


# -- a full recompute's fold is cooperative (C-2.17): chunks, closes held back meanwhile --------

SMA1500 = [{"indicator": "sma", "params": {"n": 1_500}}]


class _Deep:
    """A deep series of `GEN`: the store's read gets bars 2 000..2 999, `read` (`HistoryRead`)
    every stored bar opening in its window, at once."""

    def __init__(self) -> None:
        self.bars = [wave(i) for i in range(3_000)]

    async def tail(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        newest = self.bars[2_000:][-limit:]
        return BarTail([(GEN, b) for b in newest], since_us=0, fetched=len(newest))

    async def read(
        self, symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        return [(b.index, bar_input(b)) for b in self.bars if start_us <= b.open_time < end_us]


class _Folding:
    """Set once the engine folds its first chunk, and counting the chunks (a spy on `_fold`)."""

    def __init__(self, engine: IndicatorEngine, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started = asyncio.Event()
        self.calls = 0
        real = engine._fold

        def fold(*args: Any, **kw: Any) -> int | None:
            self.started.set()
            self.calls += 1
            return real(*args, **kw)

        monkeypatch.setattr(engine, "_fold", fold)

    async def begun(self, engine: IndicatorEngine, r: Requested) -> int:
        """Wait until the instance's read is folding; the points it has folded by then."""
        await self.started.wait()
        inst = engine._instances[(SYM, r.key)]
        assert inst.held is not None and not inst.ready
        assert engine.snapshot(SYM, r.key, 5) is None
        return len(inst.points)


async def _deep(
    monkeypatch: pytest.MonkeyPatch, **kw: Any
) -> tuple[_Deep, SeriesStore, IndicatorEngine, Requested, _Folding, Any]:
    """SMA(1 500) with history 1 000 needs 2 500 bars: it reads 500..1 999 and folds 2 500 bars,
    `PRIME_CHUNK_UPDATES` kernel updates at a time. The test's coroutine runs once the fold has
    begun."""
    deep = _Deep()
    store = SeriesStore(deep.tail)
    hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store, history=deep.read, **kw)
    folding = _Folding(engine, monkeypatch)
    (r,) = admit(engine, SMA1500, history=1_000)
    return deep, store, engine, r, folding, hold


async def test_a_read_is_folded_in_chunks_and_closes_meanwhile_are_folded_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop runs between chunks (a close lands mid-fold); the instance stays not ready, and
    the closes it held back (a new bar, then an amended one) are folded in order before it is:
    it ends as a from-scratch fold of the series as the store ends."""
    deep, store, engine, r, folding, _hold = await _deep(monkeypatch)
    late = wave(2_999).model_copy(update={"close": wave(2_999).close + 9})
    folded: list[int] = []

    async def land() -> None:
        folded.append(await folding.begun(engine, r))
        await close(store, engine, wave(3_000), generation=GEN)
        await close(store, engine, late, generation=GEN, amended=True)

    await asyncio.gather(land(), _done(engine))
    assert 0 < folded[0] < 2_500  # it ran mid-fold
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and [p.index for p in batch.points] == list(range(2_001, 3_001))
    series = [*deep.bars[500:2_999], late, wave(3_000)]
    expected = _fold(r, [bar_input(b) for b in series])
    assert _reprs([p.values for p in batch.points]) == expected[-1_000:]


async def test_a_generation_change_during_the_fold_primes_from_the_store_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deep_bars, store, engine, r, folding, _hold = await _deep(monkeypatch)

    async def land() -> None:
        await folding.begun(engine, r)
        await close(store, engine, wave(0, slot=3_001), generation=GEN + 1)  # a cold start

    await asyncio.gather(land(), _done(engine))
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and [(p.generation, p.index) for p in batch.points] == [(GEN + 1, 0)]


async def test_a_store_repair_during_the_fold_primes_from_the_store_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deep_bars, _store, engine, r, folding, _hold = await _deep(monkeypatch)

    async def land() -> None:
        await folding.begun(engine, r)
        engine.history_repair(SYM, M1, 1)

    await asyncio.gather(land(), _done(engine))
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and [p.index for p in batch.points] == list(range(2_000, 3_000))
    assert {p.values for p in batch.points} == {(None,)}  # SMA(1 500) on the store's 1 000 bars


async def test_a_new_generation_s_close_above_the_folded_index_is_never_folded_as_the_next_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of the WS delivery: a close of another generation held back while the fold ran, at
    an index above the instance's last one, is not folded as the next bar of the generation it
    read (only `_replay`'s generation check stops it): the instance ends primed from the store,
    which reset to the new generation."""
    _deep_bars, store, engine, r, folding, _hold = await _deep(monkeypatch)

    async def land() -> None:
        await folding.begun(engine, r)
        await close(store, engine, wave(3_500), generation=GEN + 1)

    await asyncio.gather(land(), _done(engine))
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None
    assert [(p.generation, p.index) for p in batch.points] == [(GEN + 1, 3_500)]


async def test_an_instance_expired_mid_fold_stops_folding_and_frees_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of the WS delivery: an instance released and past its grace while its read's fold
    yields is removed by the sweep; the fold folds no further chunk, never makes it ready, and the
    recompute's slot is free once the task ends."""
    now = [0]
    _deep_bars, _store, engine, r, folding, _hold = await _deep(monkeypatch, now_us=lambda: now[0])
    inst = engine._instances[(SYM, r.key)]
    folded: list[int] = []

    async def expire() -> None:
        await folding.begun(engine, r)
        engine.release(SYM, [r.key], "c1")
        now[0] = 30_000_000  # past its grace: the sweep below removes it
        engine.release(SYM, [], "nobody")
        folded.append(folding.calls)

    await asyncio.gather(expire(), _done(engine))
    assert folding.calls == folded[0] and not inst.ready
    assert instances(engine) == 0 and engine._busy == 0 and engine._tasks == set()


async def test_a_join_asking_less_history_never_shrinks_the_window_a_re_prime_reads() -> None:
    """Review of the WS delivery: an instance keeps the most history any admission asked of it,
    so a repair after a join that asks less still reads back the 25 bars the first one needs."""
    history = _History()
    _store, engine, _hold = await _hydrated(history)
    admit(engine, SMA20, history=5)
    await _done(engine)
    admit(engine, SMA20, history=0, consumer="c2")  # a join asking for less
    engine.history_repair(SYM, M1, 1)
    await _done(engine)
    start = wave(109).open_time - 24 * 60_000_000
    assert [call[2] for call in history.calls] == [start, start]


async def test_more_closes_than_an_instance_holds_back_prime_it_from_the_store_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At most `MAX_POINTS` closes are held back (C-2.18); past it the instance ends with the
    store's bars, which hold the newest closes."""
    _deep_bars, store, engine, r, folding, _hold = await _deep(monkeypatch)

    async def land() -> None:
        await folding.begun(engine, r)
        for i in range(3_000, 4_001):  # 1 001 closes while the fold waits
            await close(store, engine, wave(i), generation=GEN)

    await asyncio.gather(land(), _done(engine))
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and [p.index for p in batch.points] == list(range(3_001, 4_001))
    assert {p.values for p in batch.points} == {(None,)}  # SMA(1 500) on the store's 1 000 bars


async def test_stored_history_reads_pages_of_at_most_a_thousand_rows_and_yields_between() -> None:
    """C-2.17: a page's checks and conversions run without a yield, so pages are short and the
    loop runs between them (the reader here never yields itself)."""
    rows = [bar_row(wave(i), M1, generation=GEN) for i in range(2_500)]
    at = {wave(i).open_time: i + 1 for i in range(2_500)}  # a cursor -> the next row's position

    class _Pages:
        def __init__(self) -> None:
            self.limits: list[int] = []

        async def read_bars(
            self, symbol: str, spec: BarSpec, from_us: int, to_us: int, limit: int, *,
            after_us: int | None = None, at_key: BarKey | None = None,
        ) -> BarPage:  # fmt: skip
            self.limits.append(limit)
            first = 0 if after_us is None else at[after_us]
            page = rows[first : first + limit]
            more = first + limit < len(rows)
            return BarPage(page, wave(first + limit - 1).open_time if more else None, stale=False)

    pages, turns, done = _Pages(), [0], [False]

    async def ticker() -> None:
        while not done[0]:
            turns[0] += 1
            await asyncio.sleep(0)

    async def reading() -> list[tuple[int, BarInput]]:
        try:
            return await StoredHistory(pages)(SYM, M1, GEN, wave(0).open_time, 2**53)
        finally:
            done[0] = True

    got, _ = await asyncio.gather(reading(), ticker())
    assert [i for i, _ in got] == list(range(2_500))
    assert pages.limits == [1_000, 1_000, 1_000]
    assert turns[0] >= 2  # the loop ran after each full page
