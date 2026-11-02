"""#2933: a restore that storage is ahead of is refused, and the series starts a new generation.

A series saves its blob at trade 5, then closes and persists bars from trades 6-11. The process
crashes and the recorder's write-behind has lost trades 7-11, yet the tape head is still past the
watermark, so `ahead_of_tape` passes. Restoring would replay trade 6 only, and the live trades
after it would re-emit `(generation, index)` keys already stored, with other content. Before it
replays anything, the set reads every bar stored in the blob's generation above the blob's last
closed index (`BarReader.read_after`, anchored at the blob, not at now) and rebuilds them on a
scratch builder from the blob plus the tape, which emits nothing: a stored bar the scratch
builder has not closed, or closed with other content, refuses the blob (`storage_ahead`), and
the series cold-starts above the blob's generation. A read that cannot say what is stored
refuses it too. A clean tape restores in place, a time bar closed by the clock included.

The storage here is a real `BarReader` over an in-memory `bars_*` table that answers its one
statement by its binds, so the query's anchor, filter and limit are what the tests exercise.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.builder_set import (
    PERSIST_EVERY_US,
    STATE_COLD_STARTED,
    BarBuilderSet,
    BuilderFactory,
    ClosedFrontier,
    StoredAfter,
    default_factory,
    production_factory,
)
from candleviewer.bars.emit import BarEmission, EmitRouter
from candleviewer.bars.limits import MAX_NON_TIME_WINDOW_US, MAX_TAIL
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import MAX_AFTER_ROWS, BarReader, StoredRun, tail_window_us
from candleviewer.bars.rows import bar_row
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import (
    H1,
    M1,
    T3,
    TOPIC,
    V5,
    Clock,
    FakeTape,
    RecordingSink,
    blob_discards,
    settle,
)
from ._trades import SYM, trade, us

T0 = us("10:00:00")
GEN = T0 // 1000  # the first run's generation (a cold start at T0)
COLD_US = T0 + 600_000_000  # the restart, ten minutes later
REASON = "storage_ahead"
HOUR, MIN = 3_600_000_000, 60_000_000
RENKO = BarSpec(kind="renko", range_ticks=2)
RENKO_FACTORY = production_factory(lambda _s: Decimal("0.01"), renko_enabled=True)
_LIMIT = re.compile(r" LIMIT (\d+)$")


def _ticks(lo: int, hi: int) -> list[TradeEvent]:
    """Trades `lo..hi-1`, one microsecond apart (`seq` = position): three per `T3` bar."""
    return [trade(T0 + i, seq=i) for i in range(lo, hi)]


def _rising(lo: int, hi: int) -> list[TradeEvent]:
    """Trades `lo..hi-1`, each one renko brick (2 ticks of 0.01) above the last."""
    return [trade(T0 + i, px=Decimal(100) + Decimal("0.02") * i, seq=i) for i in range(lo, hi)]


async def _no_rebuild(*_: object) -> None:
    return None


class Storage:
    """The `bars_*` tables, in memory: rows keyed as the DEDUP upsert keys them
    `(ts, generation, index)`, written as `WriterSink` writes them (`bar_row`), plus every
    distinct content a `(generation, index)` was ever closed with. As a `RowFetcher` it answers
    `read_after`'s statement by its binds and its `LIMIT`."""

    name = "questdb"

    def __init__(self) -> None:
        self.rows: dict[tuple[int, int, int], dict[str, object]] = {}
        self.contents: dict[tuple[int, int], set[tuple[int, int, int]]] = {}
        self.reads: list[tuple[str, tuple[object, ...]]] = []

    async def emit(self, emission: BarEmission) -> None:
        for u in emission.updates:
            if u.kind == "close":
                b, gen = u.bar, emission.generation
                self.rows[b.open_time, gen, b.index] = bar_row(b, emission.spec, generation=gen)
                content = (b.open_time, b.close_time, b.trade_count)
                self.contents.setdefault((gen, b.index), set()).add(content)

    def keys(self) -> list[tuple[int, int]]:
        return sorted((g, i) for _, g, i in self.rows)

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.reads.append((sql, params))
        symbol, bar_param, ts, gen, after = params
        limit = _LIMIT.search(sql)
        assert limit is not None and "ORDER BY ts" in sql
        start = ts_us_from_row(ts)
        found = [
            r
            for (t, g, i), r in sorted(self.rows.items())
            if r["symbol"] == symbol and r["bar_param"] == bar_param
            and t >= start and g == gen and i > int(str(after))
        ]  # fmt: skip
        return found[: int(limit.group(1))]

    def after(self, now_us: int) -> StoredAfter:
        return BarReader(self, _no_rebuild, now_us=lambda: now_us).read_after


class CountingTape(FakeTape):
    """`FakeTape` that also counts the trades each `since` call yielded, in call order."""

    def __init__(self, trades: Sequence[TradeEvent] = ()) -> None:
        super().__init__(trades)
        self.per_read: list[int] = []

    async def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]:
        self.per_read.append(0)
        async for t in super().since(symbol, ts_us):
            self.per_read[-1] += 1
            yield t


def _set(
    root: Path,
    now_us: int,
    sinks: Sequence[object],
    store: Storage | None = None,
    **kw: object,
) -> BarBuilderSet:
    stored = store.after(now_us) if store is not None else kw.pop("stored", None)
    return BarBuilderSet(
        Bus(),
        "demo",
        EmitRouter(sinks),  # type: ignore[arg-type]  # test sinks satisfy BarSink structurally
        StateStore(root),
        now_us=Clock(now_us),
        stored=stored,  # type: ignore[arg-type]  # a StoredAfter, per test
        **kw,  # type: ignore[arg-type]  # tape / factory, per test
    )


async def _publish(s: BarBuilderSet, trades: Sequence[TradeEvent]) -> None:
    for t in trades:
        await s._bus.publish(TOPIC, t)
    await settle(s._bus, s)


async def _first_run(
    root: Path,
    store: Storage,
    spec: BarSpec = T3,
    trades: Sequence[TradeEvent] = (),
    *,
    saved_after: int = 5,
    factory: BuilderFactory = default_factory,
    start: int = T0,
) -> None:
    """`trades` (default `_ticks(0, 11)`), the periodic save after the first `saved_after` of
    them (the clock at `start` plus a minute), then a crash: no final blob. For `T3`: the save
    at trade 5 (seq 4), then trades 6-11 close bars 1 and 2, which the storage keeps."""
    trades = list(trades) or _ticks(0, 11)
    clock = Clock(start)
    s = BarBuilderSet(
        Bus(), "demo", EmitRouter([store]), StateStore(root), now_us=clock, factory=factory
    )
    await s.register(spec, SYM, "c")
    await _publish(s, trades[:saved_after])
    clock.t = start + PERSIST_EVERY_US
    await s.tick()  # the periodic save
    await _publish(s, trades[saved_after:])
    s._lanes.clear()  # crash


async def _restart(
    root: Path,
    store: Storage,
    tape: FakeTape,
    live: Sequence[TradeEvent],
    spec: BarSpec = T3,
    *,
    now_us: int = COLD_US,
    factory: BuilderFactory = default_factory,
) -> tuple[RecordingSink, BarBuilderSet, list[str]]:
    rec = RecordingSink()
    s = _set(root, now_us, [rec, store], store, tape=tape, factory=factory)
    with capture_logs() as logs:
        await s.register(spec, SYM, "c")
    await _publish(s, live)
    discarded = [e["reason"] for e in logs if e["event"] == "bars_state_blob_discarded"]
    return rec, s, discarded


async def test_restore_whose_tape_lost_the_stored_bars_starts_a_new_generation(
    tmp_path: Path,
) -> None:
    store = Storage()
    await _first_run(tmp_path, store)
    assert store.keys() == [(GEN, 0), (GEN, 1), (GEN, 2)]
    before = blob_discards(REASON)
    tape = FakeTape(_ticks(0, 7))  # trades 7-11 (seq 6-10) were lost; the head is past the mark
    rec, s, discarded = await _restart(tmp_path, store, tape, _ticks(100, 107))
    assert discarded == [REASON] and blob_discards(REASON) == before + 1
    assert STATE_COLD_STARTED in s.health_reasons()
    gens = {g for _, g, *_ in rec.seen}
    assert len(gens) == 1 and gens.pop() > GEN  # nothing was emitted in the blob's generation
    assert all(len(c) == 1 for c in store.contents.values())  # no key re-closed with new content
    await s.stop()


async def test_restore_with_an_intact_tape_stays_in_its_generation(tmp_path: Path) -> None:
    store = Storage()
    await _first_run(tmp_path, store)
    before = blob_discards(REASON)
    tape = FakeTape(_ticks(0, 11))  # every trade the stored bars came from
    rec, s, discarded = await _restart(tmp_path, store, tape, _ticks(11, 14))
    assert discarded == [] and blob_discards(REASON) == before
    assert {g for _, g, *_ in rec.seen} == {GEN}
    assert [i for _, _, k, i, _ in rec.seen if k == "close"] == [1, 2, 3]  # replay, then live
    # One statement, anchored at the blob: bars above its last closed index (0), from the open
    # time of its forming bar (bar 1, trade seq 3), in its generation.
    [(_, (_, _, ts, gen, after))] = store.reads
    assert (ts_us_from_row(ts), gen, after) == (T0 + 3, GEN, 0)
    assert all(len(c) == 1 for c in store.contents.values())
    await s.stop()


async def test_restore_whose_tape_lost_a_middle_trade_is_refused(tmp_path: Path) -> None:
    """The tape keeps as many trades as the stored bars hold, but not the same ones: the
    scratch builder closes bar 2 with other content, so the blob is refused all the same."""
    store = Storage()
    await _first_run(tmp_path, store)
    tape = FakeTape([*_ticks(0, 7), *_ticks(8, 12)])  # seq 7 lost, seq 11 recorded after it
    rec, s, discarded = await _restart(tmp_path, store, tape, _ticks(100, 103))
    assert discarded == [REASON]
    assert GEN not in {g for _, g, *_ in rec.seen}
    await s.stop()


async def test_restore_whose_tape_lost_the_closing_trade_is_refused(tmp_path: Path) -> None:
    """The tape ends at the watermark: the bar the lost trade closed is stored, but the restored
    builder still holds it open and would close it again with another trade."""
    store = Storage()
    await _first_run(tmp_path, store)
    rec, s, discarded = await _restart(tmp_path, store, FakeTape(_ticks(0, 5)), _ticks(100, 101))
    assert discarded == [REASON]
    assert GEN not in {g for _, g, *_ in rec.seen}
    await s.stop()


async def test_restore_long_after_the_crash_still_sees_the_stored_bars(tmp_path: Path) -> None:
    """M1 (#2933 review): the read is anchored at the blob, not at now. The series is leased
    three days after the crash, past the WS tail window of its 1-minute bars (about 33 h), which
    the first cut read from: it found no stored bar and let a blob through whose tape lost the
    trade that closed bar 0. Bar 1 is stored too."""
    store, start = Storage(), T0 - MIN  # the save lands at T0, bar 0 (the T0 minute) forming
    trades = [trade(T0 + 1_000_000, seq=1), trade(T0 + 2_000_000, seq=2)]
    trades += [trade(T0 + s * 1_000_000, seq=i) for i, s in ((3, 70), (4, 80), (5, 130))]
    await _first_run(tmp_path, store, M1, trades, saved_after=2, start=start)
    gen = start // 1000
    assert store.keys() == [(gen, 0), (gen, 1)]
    later = T0 + 3 * 24 * HOUR
    assert later - T0 > tail_window_us(M1, MAX_TAIL)  # the old read would have seen nothing
    tape = FakeTape(trades[:3])  # seq 4 and 5 lost: bar 1 is rebuilt with one trade, not two
    rec, s, discarded = await _restart(tmp_path, store, tape, (), M1, now_us=later)
    assert discarded == [REASON]
    assert gen not in {g for _, g, *_ in rec.seen}
    [(_, (_, _, ts, read_gen, after))] = store.reads
    assert (ts_us_from_row(ts), read_gen, after) == (T0, gen, -1)  # bar 0's open, not now
    await s.stop()


async def test_restore_whose_older_bar_lost_a_trade_is_refused(tmp_path: Path) -> None:
    """M3 (#2933 review): every stored bar above the blob is compared, not only the newest.
    The tape lost a trade inside hour bar 0 while bar 1, the newest stored, rebuilds exactly:
    the first cut compared bar 1 alone and restored the blob."""
    store = Storage()
    trades = [trade(T0 + s * 1_000_000, seq=i) for i, s in enumerate((1, 2), start=1)]
    later = [(3, 10 * 60), (4, 61 * 60), (5, 62 * 60), (6, 125 * 60)]
    trades += [trade(T0 + s * 1_000_000, seq=i) for i, s in later]
    await _first_run(tmp_path, store, H1, trades, saved_after=2)
    assert store.keys() == [(GEN, 0), (GEN, 1)]
    tape = FakeTape([t for t in trades if t.seq != 3])  # inside bar 0, after the watermark
    rec, s, discarded = await _restart(tmp_path, store, tape, (), H1, now_us=T0 + 3 * HOUR)
    assert discarded == [REASON]
    assert GEN not in {g for _, g, *_ in rec.seen}
    await s.stop()


async def test_the_tape_read_stops_at_the_newest_stored_bar(tmp_path: Path) -> None:
    """M2 (#2933 review): the check reads the tape, in `ts` order, only until the scratch
    builder closes the newest stored bar (bar 2, closed by seq 8): five trades (seq 4-8), not
    the 36 to the head that the replay then reads."""
    store = Storage()
    await _first_run(tmp_path, store)
    tape = CountingTape(_ticks(0, 40))
    _, s, discarded = await _restart(tmp_path, store, tape, ())
    assert discarded == []
    assert tape.per_read == [5, 36]  # the check, then the replay (seq 4-39)
    await s.stop()


async def test_restore_of_a_time_bar_closed_by_the_clock_stays_in_place(tmp_path: Path) -> None:
    """Storage holds an hour bar the clock closed after the save; no trade after the watermark.
    The scratch builder runs the clock to now too, so it closes that bar the same way."""
    store, clock = Storage(), Clock(T0)
    s1 = BarBuilderSet(Bus(), "demo", EmitRouter([store]), StateStore(tmp_path), now_us=clock)
    await s1.register(H1, SYM, "c")
    await _publish(s1, [trade(T0 + 1_000_000, seq=1)])
    clock.t = T0 + PERSIST_EVERY_US
    await s1.tick()  # the save, the bar still open
    blob = StateStore(tmp_path).path(SYM, H1.spec_hash)
    saved = blob.read_bytes()
    clock.t = T0 + HOUR
    await s1.tick()  # the clock closes bar 0, stored
    blob.write_bytes(saved)  # the crash lost the save that followed the close
    assert store.keys() == [(GEN, 0)]
    s1._lanes.clear()  # crash
    tape = FakeTape([trade(T0 + 1_000_000, seq=1)])
    rec = RecordingSink()
    s2 = _set(tmp_path, T0 + 2 * HOUR, [rec, store], store, tape=tape)
    with capture_logs() as logs:
        await s2.register(H1, SYM, "c")
    assert not [e for e in logs if e["event"] == "bars_state_blob_discarded"]
    await s2.tick()
    assert [(g, k, i) for _, g, k, i, _ in rec.seen] == [(GEN, "close", 0)]
    await s2.stop()


SPECS = pytest.mark.parametrize(
    ("spec", "trades", "saved_after", "lost", "factory"),
    [
        # Volume bars of 5 lots: bar 0 closed at the save (seq 6), bars 1 and 2 stored after it.
        (V5, _ticks(0, 17), 7, 9, default_factory),
        # Renko bricks, one per rising trade: bricks 0-3 at the save, 4-9 stored after it.
        (RENKO, _rising(0, 11), 5, 8, RENKO_FACTORY),
    ],
    ids=["volume", "renko"],
)


@SPECS
async def test_restore_of_a_non_tick_series_with_an_intact_tape_stays(
    tmp_path: Path,
    spec: BarSpec,
    trades: list[TradeEvent],
    saved_after: int,
    lost: int,
    factory: BuilderFactory,
) -> None:
    store = Storage()
    await _first_run(tmp_path, store, spec, trades, saved_after=saved_after, factory=factory)
    tape = FakeTape(trades)
    rec, s, discarded = await _restart(tmp_path, store, tape, (), spec, factory=factory)
    assert discarded == [] and {g for _, g, *_ in rec.seen} == {GEN}
    assert all(len(c) == 1 for c in store.contents.values())
    await s.stop()


@SPECS
async def test_restore_of_a_non_tick_series_whose_tape_lost_trades_is_refused(
    tmp_path: Path,
    spec: BarSpec,
    trades: list[TradeEvent],
    saved_after: int,
    lost: int,
    factory: BuilderFactory,
) -> None:
    store = Storage()
    await _first_run(tmp_path, store, spec, trades, saved_after=saved_after, factory=factory)
    tape = FakeTape(trades[:lost])  # the head is still past the watermark
    rec, s, discarded = await _restart(tmp_path, store, tape, (), spec, factory=factory)
    assert discarded == [REASON]
    assert GEN not in {g for _, g, *_ in rec.seen}
    await s.stop()


async def test_restore_with_nothing_stored_in_its_generation_reads_no_tape_twice(
    tmp_path: Path,
) -> None:
    store = Storage()
    await _first_run(tmp_path, store)
    store.rows.clear()  # the writer lost every row: nothing to be ahead of
    tape = FakeTape(_ticks(0, 11))
    rec, s, discarded = await _restart(tmp_path, store, tape, ())
    assert discarded == [] and {g for _, g, *_ in rec.seen} == {GEN}
    assert tape.reads == 7  # trades 4-10 once: the watermark's own and the six after it
    await s.stop()


async def test_an_incomplete_storage_read_refuses_the_blob(tmp_path: Path) -> None:
    """Unknown fails closed: a read that cannot say which bars are stored (its row limit, the
    window cap, a row it cannot use) refuses the blob, counted, with no tape read."""
    store = Storage()
    await _first_run(tmp_path, store)
    before = blob_discards(REASON)

    async def cut(symbol: str, spec: BarSpec, gen: int, after: int, from_us: int) -> StoredRun:
        return StoredRun([], complete=False)

    tape = CountingTape(_ticks(0, 11))
    s = _set(tmp_path, COLD_US, [], stored=cut, tape=tape)
    with capture_logs() as logs:
        await s.register(T3, SYM, "c")
    assert [e["reason"] for e in logs if e["event"] == "bars_state_blob_discarded"] == [REASON]
    assert blob_discards(REASON) == before + 1 and tape.per_read == []
    await s.stop()


async def test_a_blob_older_than_the_window_cap_is_refused_without_a_read(
    tmp_path: Path,
) -> None:
    """Its bars cannot be read inside SR-E12-02's cap: unknown, so refused, and no statement is
    sent."""
    store = Storage()
    await _first_run(tmp_path, store)
    later = T0 + MAX_NON_TIME_WINDOW_US + 24 * HOUR
    tape = FakeTape(_ticks(0, 11))
    _, s, discarded = await _restart(tmp_path, store, tape, (), now_us=later)
    assert discarded == [REASON] and store.reads == []
    await s.stop()


@pytest.mark.parametrize("exc", [OSError("storage unavailable"), TimeoutError()])
async def test_a_failing_storage_read_refuses_the_blob(tmp_path: Path, exc: Exception) -> None:
    """Unknown fails closed: a failed or timed-out stored read refuses the blob, counted, and
    the series starts a new generation (the blob is replaced by the cold start's floor)."""
    store = Storage()
    await _first_run(tmp_path, store)
    blob = StateStore(tmp_path).path(SYM, T3.spec_hash).read_bytes()

    async def broken(symbol: str, spec: BarSpec, gen: int, after: int, from_us: int) -> StoredRun:
        raise exc

    before = blob_discards(REASON)
    rec = RecordingSink()
    s = _set(tmp_path, COLD_US, [rec, store], stored=broken, tape=FakeTape(_ticks(0, 11)))
    with capture_logs() as logs:
        await s.register(T3, SYM, "c")
    await _publish(s, _ticks(100, 107))
    discarded = [e["reason"] for e in logs if e["event"] == "bars_state_blob_discarded"]
    assert discarded == [REASON] and blob_discards(REASON) == before + 1
    failed = [e for e in logs if e["event"] == "bars_storage_read_failed"]
    assert [e["error_type"] for e in failed] == [type(exc).__name__]
    assert "storage unavailable" not in str(failed)
    gens = {g for _, g, *_ in rec.seen}
    assert len(gens) == 1 and gens.pop() > GEN
    assert StateStore(tmp_path).path(SYM, T3.spec_hash).read_bytes() != blob
    await s.stop()


async def test_a_cancelled_storage_read_propagates(tmp_path: Path) -> None:
    store = Storage()
    await _first_run(tmp_path, store)
    blob = StateStore(tmp_path).path(SYM, T3.spec_hash).read_bytes()

    async def cancelled(
        symbol: str, spec: BarSpec, gen: int, after: int, from_us: int
    ) -> StoredRun:
        raise asyncio.CancelledError

    s = _set(tmp_path, COLD_US, [], stored=cancelled, tape=FakeTape(_ticks(0, 11)))
    with pytest.raises(asyncio.CancelledError):
        await s.register(T3, SYM, "c")
    assert StateStore(tmp_path).path(SYM, T3.spec_hash).read_bytes() == blob
    await s.stop()


@pytest.mark.parametrize(
    "spec",
    [
        H1,
        T3,
        BarSpec(kind="volume", volume_threshold=Decimal(5)),
        BarSpec(kind="delta", delta_threshold=Decimal(5)),
        BarSpec(kind="range", range_ticks=2),
        RENKO,
    ],
)
def test_every_production_builder_reports_its_closed_frontier(spec: BarSpec) -> None:
    builder = RENKO_FACTORY(spec, SYM)
    assert isinstance(builder, ClosedFrontier)
    assert builder.closed_through() == -1 and builder.forming_open_us() is None


def test_closed_frontier_counts_closed_bars_only() -> None:
    builder = default_factory(T3, SYM)
    assert isinstance(builder, ClosedFrontier)
    for t in _ticks(0, 4):
        builder.on_trade(t)
    assert builder.closed_through() == 0  # bar 0 closed, bar 1 forming
    assert builder.forming_open_us() == T0 + 3
    for t in _ticks(4, 6):
        builder.on_trade(t)
    assert builder.closed_through() == 1 and builder.forming_open_us() is None


def test_time_builder_forming_open_is_its_bucket_start() -> None:
    builder = default_factory(H1, SYM)
    assert isinstance(builder, ClosedFrontier)
    builder.on_trade(trade(T0 + 5 * MIN, seq=1))
    assert builder.forming_open_us() == T0


def test_read_after_row_cap_is_the_tail_cap() -> None:
    assert MAX_AFTER_ROWS == MAX_TAIL
