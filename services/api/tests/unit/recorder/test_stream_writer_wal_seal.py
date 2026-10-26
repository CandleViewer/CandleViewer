"""#2475: a WAL-drop gap window is sealed by the first row that reaches QuestDB or the WAL, so no
`backpressure_drop` gap ever spans a written `exch_ts` (C-2.14). Fakes and `tmp_path` only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from candleviewer.recorder.wal import RUNS_DIR, WalRecord
from candleviewer.recorder.writer import StreamWriter
from tests.unit.recorder._writer_helpers import T0, FakeClock, make_writer, trade


class WalScript:
    """Wraps the trades lane's real `append`: each call accepts at most `accept` records (None =
    as many as the budget allows) and logs what was accepted and refused."""

    def __init__(self, w: StreamWriter) -> None:
        self.wal = w._lanes["trades"].wal
        self.real = self.wal.append
        self.wal.append = self.append  # type: ignore[method-assign]  # scripted WAL refusals
        self.accept: int | None = None
        self.accepted: list[tuple[str, int]] = []
        self.refused: list[tuple[str, int]] = []

    def append(self, records: list[WalRecord]) -> int:
        n = len(records) if self.accept is None else min(self.accept, len(records))
        got = self.real(records[:n]) if n else 0
        self.accepted += [(r.symbol, r.exch_ts) for r in records[:got]]
        self.refused += [(r.symbol, r.exch_ts) for r in records[got:]]
        return got


def _at(us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us)


def _spans(gaps: list[dict[str, object]]) -> list[tuple[object, object]]:
    return [(g["start"], g["end"]) for g in gaps]


async def _pump(w: StreamWriter, clock: FakeClock) -> None:
    clock.advance(0.2)
    await w.pump("trades")


async def test_wal_drop_refuse_accept_refuse_before_flush_records_two_gaps(
    tmp_path: Path,
) -> None:
    """Given the WAL refuses rows, then accepts some, then refuses again before a flush;
    When gaps are flushed; Then two gaps are recorded and neither contains a written exch_ts."""
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    for i in (1, 2):
        await w.on_trade(trade(i))
    await _pump(w, clock)  # refused: window [t1, t2]
    wal.accept = None
    await w.on_trade(trade(3))
    await _pump(w, clock)  # accepted: t3 is in the WAL, the window ends here
    wal.accept = 0
    for i in (4, 5):
        await w.on_trade(trade(i))
    await _pump(w, clock)  # refused again: a new window [t4, t5]
    await w.flush_gaps()
    assert wal.accepted == [("BTCUSDT", T0 + 3)]
    assert _spans(store.gaps) == [(_at(T0 + 1), _at(T0 + 2)), (_at(T0 + 4), _at(T0 + 5))]


async def test_wal_drop_partial_append_seals_before_the_refused_suffix(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    await w.on_trade(trade(1))
    await _pump(w, clock)
    wal.accept = 1
    for i in (2, 3):
        await w.on_trade(trade(i))
    await _pump(w, clock)  # t2 accepted, t3 refused in the same append
    await w.flush_gaps()
    assert _spans(store.gaps) == [(_at(T0 + 1), _at(T0 + 2)), (_at(T0 + 3), _at(T0 + 4))]


async def test_wal_drop_window_sealed_by_a_questdb_write(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    await w.on_trade(trade(1))
    await _pump(w, clock)  # dropped: window [t1]
    sink.down.clear()
    await w.recover()  # empty WAL: the lane leaves spill mode
    await w.on_trade(trade(2))
    await _pump(w, clock)  # t2 reaches QuestDB
    sink.down.add("*")
    await w.on_trade(trade(3))
    await _pump(w, clock)  # dropped again
    await w.flush_gaps()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t2"]
    assert _spans(store.gaps) == [(_at(T0 + 1), _at(T0 + 2)), (_at(T0 + 3), _at(T0 + 4))]


@pytest.mark.parametrize(
    ("widen", "second"),
    [(False, []), (True, [(_at(T0 + 2), _at(T0 + 3))])],
    ids=["sealed_as_persisted", "widened_then_sealed"],
)
async def test_flush_gaps_window_sealed_in_flight_is_not_persisted_twice(
    tmp_path: Path, widen: bool, second: list[tuple[datetime, datetime]]
) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    for i in (1, 2):
        await w.on_trade(trade(i))
    await _pump(w, clock)  # window [t1, t2]
    real = store.record_live_gap
    fired = False

    async def in_flight(**kw: object) -> bool:
        nonlocal fired
        if not fired:  # while the first insert is in flight: (widen and) seal the window
            fired = True
            if widen:
                await w.on_trade(trade(3))
                await w.pump("trades")
            wal.accept = None
            await w.on_trade(trade(4))
            await w.pump("trades")
        return await real(**kw)  # type: ignore[arg-type]  # forwarded as received

    store.record_live_gap = in_flight  # type: ignore[method-assign]  # inject the race
    await w.flush_gaps()
    await w.flush_gaps()
    assert _spans(store.gaps) == [(_at(T0 + 1), _at(T0 + 2)), *second]
    assert not w.pending_gaps()


async def test_replay_keeps_damaged_marker_while_a_sealed_window_is_unpersisted(
    tmp_path: Path,
) -> None:
    """A write that seals the damaged window while its gap insert fails must not let
    `ack_damaged` clear the durable marker."""
    w, sink, store, _, clock = await make_writer(
        tmp_path, flush_rows=2, replay_chunk_rows=2, max_queue_rows=1
    )
    sink.down.add("*")
    for i in range(4):
        await w.on_trade(trade(i))
    await _pump(w, clock)
    await w.recover()  # runs/ built; the write fails
    runs = tmp_path / "wal" / "trades" / RUNS_DIR
    victim = runs / "000001.run"
    victim.write_bytes(victim.read_bytes()[:5])
    store.session = False  # the gap cannot be persisted yet
    real = store.record_live_gap

    async def sealing(**kw: object) -> bool:
        await w.on_trade(trade(10))  # spilled straight to the WAL: seals the damaged window
        return await real(**kw)  # type: ignore[arg-type]  # forwarded as received

    store.record_live_gap = sealing  # type: ignore[method-assign]  # inject the write
    await w.recover()  # verify -> damaged window -> gap insert fails; replay still down
    assert (runs / "DAMAGED").exists()
    assert w.pending_gaps()


async def test_stop_sealed_unpersisted_window_raises_critical_event(tmp_path: Path) -> None:
    w, sink, store, events, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    store.session = False
    sink.down.add("*")
    wal.accept = 0
    await w.on_trade(trade(1))
    await _pump(w, clock)
    wal.accept = None
    await w.on_trade(trade(2))
    await _pump(w, clock)  # sealed, still without a session
    await w.stop()
    (event,) = [e for e in events.events if e.kind == "recorder_gap_unpersisted"]
    assert f"{T0 + 1}..{T0 + 1}" in event.message


SYMS = ("BTCUSDT", "ETHUSDT")
KINDS = ("trade", "trade", "trade", "pump", "pump", "pump", "sink", "recover", "flush")


@settings(
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(st.lists(st.tuples(st.sampled_from(KINDS), st.integers(0, 4)), min_size=1, max_size=60))
# Pinned interleavings (derandomized generation alone does not reach them): queue-full spill,
# then a partial append; and a sink outage with refuse / accept / refuse pumps.
@example(steps=[("pump", 0), *[("trade", 0)] * 6, ("pump", 1)])
@example(
    steps=[
        *[("sink", 1), ("trade", 0), ("pump", 0), ("trade", 1), ("trade", 0), ("pump", 4)],
        *[("trade", 0), ("trade", 1), ("pump", 0), ("flush", 0), ("recover", 4), ("flush", 1)],
    ]
)
async def test_wal_drop_no_gap_contains_a_written_exch_ts(
    tmp_path_factory: pytest.TempPathFactory, steps: list[tuple[str, int]]
) -> None:
    """Random interleavings of admits, sink outages, WAL refusals (whole and partial), pumps,
    replays and gap flushes: no persisted gap holds a row that reached QuestDB or the WAL,
    and every refused row lies inside a persisted gap."""
    w, sink, store, _, clock = await make_writer(
        tmp_path_factory.mktemp("wal"), max_queue_rows=3, flush_rows=4
    )
    w.seed(SYMS)
    wal = WalScript(w)
    for i, (kind, arg) in enumerate(steps, start=1):
        if kind == "trade":
            await w.on_trade(trade(i, SYMS[arg % 2]))
        elif kind == "sink":
            sink.down = {"*"} if arg % 2 else set()
        elif kind in ("pump", "recover"):  # `arg` caps this step's WAL appends (4 = no cap)
            wal.accept = None if arg == 4 else arg
            clock.advance(0.3)
            await (w.pump("trades") if kind == "pump" else w.recover())
        else:
            store.session = arg != 0
            await w.flush_gaps()
    store.session = True
    await w.flush_gaps()
    written = {(str(r["symbol"]), int(str(r["ts"]))) for r in sink.rows("trades")}
    written |= set(wal.accepted)
    for gap in store.gaps:
        start, end = gap["start"], gap["end"]
        inside = [(s, t) for s, t in written if s == gap["symbol"] and start <= _at(t) < end]  # type: ignore[operator]  # datetimes
        assert not inside, (gap, inside)
    for sym, t in wal.refused:
        assert any(
            g["symbol"] == sym and g["start"] <= _at(t) <= g["end"]  # type: ignore[operator]  # datetimes
            for g in store.gaps
        ), (sym, t)
    assert not w.pending_gaps()
