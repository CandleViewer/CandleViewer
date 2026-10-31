"""C-13.6 #10 (datastore outage), E16-Q04: QuestDB down under the recorder, at smoke scale.

The real `StreamWriter` and its on-disk WAL (`tmp_path`), fed by the fixture-derived E16-Q04 mix,
over a sink that refuses every write while "QuestDB" is down (the ILP seam). The outage lasts 2 s
of virtual time (the ticket's 2 minutes is the nightly-at-scale DoD item, BQ-6); nothing sleeps.
- A short outage spills to the WAL and replays in `exch_ts` order once QuestDB is back: every
  produced row lands exactly once, no gap, no critical event.
- An outage longer than the WAL budget drops the rest into `backpressure_drop` gaps with one
  critical event per (symbol, stream) episode, and still balances: produced == written + dropped,
  and no gap covers a written row (C-2.14) past its first instant. At that instant it can: a
  book delta is one row per level, all at one `exch_ts`, and the WAL budget can refuse a message's
  later levels after taking its first ones, so the written prefix and the gap share that `exch_ts`
  (observed; SCENARIOS.md "Findings").
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from bench.recorder.generator import Delta, Mix
from bench.recorder.harness import dispatch
from candleviewer.recorder.writer import (
    GAP_CAUSE,
    STREAM_KIND,
    STREAMS,
    StreamWriter,
    WriterConfig,
)
from tests.unit.recorder._writer_helpers import (
    OPEN_GATE,
    T0,
    FakeClock,
    FakeEvents,
    FakeSink,
    FakeStore,
    FsyncCounter,
)

pytestmark = pytest.mark.chaos
SYMBOLS: Final = ("BTCUSDT", "ETHUSDT")
STEP_S: Final = 0.2
OUTAGE_S: Final = 2.0
PER_STEP: Final = 40
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class Outage:
    def __init__(self, tmp_path: Path, wal_max_bytes: int = 1 << 30) -> None:
        self.sink, self.store, self.events = FakeSink(), FakeStore(), FakeEvents()
        self.clock = FakeClock()
        self.writer = StreamWriter(
            lambda _s: self.sink, self.store, self.events,
            WriterConfig(wal_dir=tmp_path / "wal", env="demo", wal_max_bytes=wal_max_bytes),
            clock=self.clock, wall_clock_us=lambda: T0 + int(self.clock.t * 1e6),
            fsync=FsyncCounter(), disk_gate=OPEN_GATE,
        )  # fmt: skip
        self.mix = Mix(SYMBOLS, seed=29, depth=200)
        self.ts = T0
        #: Rows produced per (stream kind, symbol, exch_ts), counted as the mix counts them.
        self.sent: Counter[tuple[str, str, datetime]] = Counter()

    async def step(self, n: int = PER_STEP) -> None:
        for _ in range(n):
            self.ts += 1_000
            kind, ev = self.mix.next(self.ts)
            rows = len(ev.bids) + len(ev.asks) if isinstance(ev, Delta) else 1
            at = _EPOCH + timedelta(microseconds=ev.ts_event)
            self.sent[(STREAM_KIND[kind], ev.symbol, at)] += rows
            await dispatch(self.writer, kind, ev)
        self.clock.advance(STEP_S)
        for stream in STREAMS:
            await self.writer.pump(stream)

    async def run_outage(self) -> None:
        await self.writer.open()
        self.writer.seed(list(SYMBOLS))
        await self.step()  # healthy
        self.sink.down.add("*")  # QuestDB stops answering
        for _ in range(round(OUTAGE_S / STEP_S)):
            await self.step()
        assert any(self.writer.is_spilling(s) for s in STREAMS), "the outage reached the WAL"
        self.sink.down.clear()  # QuestDB is back: the readiness probe calls `recover()`
        await self.writer.recover()
        for _ in range(20):
            await self.step(0)
        await self.writer.flush_gaps()
        await self.writer.flush_counters()

    def rows(self) -> list[dict[str, object]]:
        return [r for table in self.sink.flushed.values() for r in table]

    def produced(self) -> int:
        return sum(self.mix.produced_rows.values())

    def dropped(self) -> int:
        return sum(kw["messages_dropped"] for _, kw in self.store.counters)


def _keys(rows: list[dict[str, object]]) -> Counter[tuple[tuple[str, str], ...]]:
    return Counter(tuple(sorted((k, repr(v)) for k, v in r.items())) for r in rows)


async def test_questdb_down_spills_then_replays_without_duplicates_or_gap(tmp_path: Path) -> None:
    o = Outage(tmp_path)
    try:
        await o.run_outage()
        rows = o.rows()
        assert len(rows) == o.produced(), "INVARIANT: every produced row written"
        assert max(_keys(rows).values()) == 1, "INVARIANT: replay wrote no row twice"
        assert o.store.gaps == [] and o.dropped() == 0, "a 2 s outage fits the WAL"
        assert not [e for e in o.events.events if e.severity == "critical"]
        assert o.writer.spill_bytes == 0 and o.writer.backlog_rows == 0, "WAL drained"
    finally:
        await o.writer.stop()


async def test_wal_exhausted_writes_backpressure_drop_gap_and_critical_event(
    tmp_path: Path,
) -> None:
    o = Outage(tmp_path, wal_max_bytes=16 * 1024)  # far below 2 s of the mix
    try:
        await o.run_outage()
        rows = o.rows()
        assert o.dropped() > 0 and o.store.gaps, "the WAL budget ran out"
        assert {g["cause"] for g in o.store.gaps} == {GAP_CAUSE}
        assert len(rows) + o.dropped() == o.produced(), "INVARIANT: every lost row is gap-accounted"
        critical = [e for e in o.events.events if e.severity == "critical"]
        assert critical and {e.kind for e in critical} == {"recorder_wal_full"}
        assert max(_keys(rows).values()) == 1
        written: Counter[tuple[str, str, datetime]] = Counter(
            (
                STREAM_KIND[table],
                str(r["symbol"]),
                _EPOCH + timedelta(microseconds=int(str(r["ts"]))),
            )
            for table, trows in o.sink.flushed.items()
            if table in STREAM_KIND
            for r in trows
        )
        gaps: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}
        for g in o.store.gaps:
            lo, hi = g["start"], g["end"]
            assert isinstance(lo, datetime) and isinstance(hi, datetime)
            gaps.setdefault((str(g["stream"]), str(g["symbol"])), []).append((lo, hi))
        # C-2.14, ruled (coordinator, 2026-10-31, PR #5259): a gap may share its first exch_ts
        # with the written prefix of a message the WAL budget split, but (a) every produced row
        # that was not written lies inside a `backpressure_drop` gap for its (stream, symbol), and
        # nothing is written strictly after a gap's first instant; (b) the replayer resyncs at
        # the gap: tests/unit/replay/test_replay_books.py::
        # test_a_gap_at_a_split_delta_resyncs_and_never_presents_the_partial_book
        unwritten = o.sent - written
        assert sum(unwritten.values()) == o.dropped(), "the oracle sees every dropped row"
        split = 0
        for (stream, symbol, at), n in unwritten.items():
            covering = [(lo, hi) for lo, hi in gaps.get((stream, symbol), []) if lo <= at <= hi]
            assert covering, f"{n} unwritten {stream} {symbol} row(s) at {at} are in no gap"
            split += written[(stream, symbol, at)] > 0
        for (stream, symbol), spans in gaps.items():
            for lo, hi in spans:
                inside = [w for w in written if w[:2] == (stream, symbol) and lo < w[2] <= hi]
                assert inside == [], f"gap {(stream, symbol, lo, hi)} spans a written row"
        produced_kinds = {k[0] for k in o.sent}
        extra = {k: n for k, n in (written - o.sent).items() if k[0] in produced_kinds}
        assert extra == {}, "nothing written that was not produced"
        assert split >= 1, "seed 29 splits a delta (SCENARIOS.md Findings): the pin is exercised"
    finally:
        await o.writer.stop()
