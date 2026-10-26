"""#2475: a WAL-drop gap window is sealed by the first newer row that reaches QuestDB or the WAL,
so (for per-key monotone delivery) no `backpressure_drop` gap spans a written `exch_ts`, and no
dropped row is ever left outside a gap (C-2.14). Fakes and `tmp_path` only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from candleviewer.recorder.wal import RUNS_DIR, WalRecord
from candleviewer.recorder.writer import DiskGate, StreamWriter
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


class Halt:
    """A disk gate whose halt is flipped by the test; no symbol holds a position."""

    def __init__(self, w: StreamWriter) -> None:
        self.on = False
        w._gate = DiskGate(halted=lambda: self.on, position_open=lambda _symbol: False)


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


async def test_flush_gaps_gate_window_sealed_during_a_drop_insert_is_kept_whole(
    tmp_path: Path,
) -> None:
    """Review repro: only the in-flight window's own sealed copy may be trimmed."""
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal, gate = WalScript(w), Halt(w)
    sink.down.add("*")
    wal.accept = 0
    for i, ts in ((1, 150), (2, 160)):
        await w.on_trade(trade(i, ts=T0 + ts))
    await _pump(w, clock)  # drop window [150, 160]
    gate.on = True
    for i, ts in ((3, 100), (4, 200)):
        await w.on_trade(trade(i, ts=T0 + ts))  # gate window [100, 200]
    real = store.record_live_gap
    fired = False

    async def in_flight(**kw: object) -> bool:
        nonlocal fired
        if not fired:
            fired, gate.on = True, False
            await w.on_trade(trade(5, ts=T0 + 300))  # admitted: seals the gate window
        return await real(**kw)  # type: ignore[arg-type]  # forwarded as received

    store.record_live_gap = in_flight  # type: ignore[method-assign]  # inject the race
    await w.flush_gaps()
    await w.flush_gaps()
    assert _spans(store.gaps) == [(_at(T0 + 150), _at(T0 + 160)), (_at(T0 + 100), _at(T0 + 200))]


async def test_flush_gaps_trims_only_the_in_flight_windows_own_copy(tmp_path: Path) -> None:
    """Gate window A, the in-flight window W and gate window B are sealed, in that order,
    during W's insert, and a new drop window opens: only W's copy is dropped."""
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal, gate = WalScript(w), Halt(w)
    sink.down.add("*")
    wal.accept = 0
    for i, ts in ((1, 150), (2, 160)):
        await w.on_trade(trade(i, ts=T0 + ts))
    await _pump(w, clock)  # W = [150, 160]
    real = store.record_live_gap
    fired = False

    async def gated(*stamps: int) -> None:
        gate.on = True
        for ts in stamps:
            await w.on_trade(trade(ts, ts=T0 + ts))
        gate.on = False

    async def in_flight(**kw: object) -> bool:
        nonlocal fired
        if not fired:
            fired = True
            await gated(155, 158)
            wal.accept = None
            await w.on_trade(trade(159, ts=T0 + 159))  # seals A; in the WAL, older than W
            await w.on_trade(trade(170, ts=T0 + 170))
            await w.pump("trades")  # 170 is newer: seals W
            await gated(165, 200)
            await w.on_trade(trade(300, ts=T0 + 300))  # seals B
            await w.pump("trades")
            wal.accept = 0
            await w.on_trade(trade(175, ts=T0 + 175))
            await w.pump("trades")  # a new drop window
        return await real(**kw)  # type: ignore[arg-type]  # forwarded as received

    store.record_live_gap = in_flight  # type: ignore[method-assign]  # inject the race
    await w.flush_gaps()
    await w.flush_gaps()
    assert _spans(store.gaps) == [
        (_at(T0 + a), _at(T0 + b)) for a, b in ((150, 160), (155, 158), (165, 200), (175, 176))
    ]


async def test_flush_gaps_window_widened_below_in_flight_keeps_its_early_rows(
    tmp_path: Path,
) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    for i, ts in ((1, 150), (2, 160)):
        await w.on_trade(trade(i, ts=T0 + ts))
    await _pump(w, clock)  # window [150, 160]
    real = store.record_live_gap
    fired = False

    async def in_flight(**kw: object) -> bool:
        nonlocal fired
        if not fired:  # a late drop widens the window below the persisted start
            fired = True
            await w.on_trade(trade(3, ts=T0 + 100))
            await w.pump("trades")
        return await real(**kw)  # type: ignore[arg-type]  # forwarded as received

    store.record_live_gap = in_flight  # type: ignore[method-assign]  # inject the race
    await w.flush_gaps()
    await w.flush_gaps()
    assert _spans(store.gaps) == [(_at(T0 + 150), _at(T0 + 160)), (_at(T0 + 100), _at(T0 + 160))]


async def test_wal_drop_written_row_inside_the_open_window_keeps_it_open(tmp_path: Path) -> None:
    """Out-of-order: a late written row inside [lo, hi] never seals (coverage over precision)."""
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    for i, ts in ((1, 1), (2, 10)):
        await w.on_trade(trade(i, ts=T0 + ts))
    await _pump(w, clock)  # window [1, 10]
    wal.accept = None
    await w.on_trade(trade(3, ts=T0 + 5))
    await _pump(w, clock)  # written, but inside the window
    wal.accept = 0
    await w.on_trade(trade(4, ts=T0 + 11))
    await _pump(w, clock)
    await w.flush_gaps()
    assert _spans(store.gaps) == [(_at(T0 + 1), _at(T0 + 11))]


async def test_replay_of_older_wal_rows_does_not_seal_a_newer_window(tmp_path: Path) -> None:
    w, sink, _, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 1
    for i in (1, 2):
        await w.on_trade(trade(i))
    await _pump(w, clock)  # t1 in the WAL, t2 dropped: window [t2]
    sink.down.clear()
    await w.recover()  # t1 replayed: older than the window
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1"]
    assert ("BTCUSDT", "trades") in w._gaps


async def test_flush_gaps_overlapping_calls_persist_a_window_once(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path)
    wal = WalScript(w)
    sink.down.add("*")
    wal.accept = 0
    await w.on_trade(trade(1))
    await _pump(w, clock)
    real = store.record_live_gap

    async def slow(**kw: object) -> bool:
        for _ in range(5):  # yield to the other flush (no wall-clock sleep)
            await asyncio.sleep(0)
        return await real(**kw)  # type: ignore[arg-type]  # forwarded as received

    store.record_live_gap = slow  # type: ignore[method-assign]  # widen the race window
    await asyncio.gather(w.flush_gaps(), w.flush_gaps())
    assert _spans(store.gaps) == [(_at(T0 + 1), _at(T0 + 2))]


SYMS = ("BTCUSDT", "ETHUSDT")
KINDS = ("trade", "trade", "trade", "pump", "pump", "pump", "sink", "gate", "recover", "flush")


@settings(
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(st.lists(st.tuples(st.sampled_from(KINDS), st.integers(0, 4)), min_size=1, max_size=60))
# Pinned interleavings (derandomized generation alone does not reach them): queue-full spill,
# then a partial append; a sink outage with refuse / accept / refuse pumps; a late written row
# inside an open window; gate and WAL windows open together.
@example(steps=[("pump", 0), *[("trade", 0)] * 6, ("pump", 1)])
@example(
    steps=[
        *[("sink", 1), ("trade", 0), ("pump", 0), ("trade", 1), ("trade", 0), ("pump", 4)],
        *[("trade", 0), ("trade", 1), ("pump", 0), ("flush", 0), ("recover", 4), ("flush", 1)],
    ]
)
@example(
    steps=[
        *[("sink", 1), ("trade", 0), ("pump", 0), ("trade", 0), ("pump", 0)],
        *[("trade", 4), ("pump", 4), ("trade", 0), ("pump", 0)],
    ]
)
@example(
    steps=[
        *[("sink", 1), ("trade", 0), ("trade", 0), ("pump", 0), ("gate", 1), ("trade", 4)],
        *[("trade", 0), ("gate", 0), ("trade", 0), ("flush", 1), ("pump", 0)],
    ]
)
async def test_wal_drop_no_gap_contains_a_written_exch_ts(
    tmp_path_factory: pytest.TempPathFactory, steps: list[tuple[str, int]]
) -> None:
    """Random interleavings of admits (some late), gate halts, sink outages, WAL refusals
    (whole and partial), pumps, replays and gap flushes. Every dropped row (gate or WAL) lies
    in a persisted gap; when each symbol's rows arrive in `exch_ts` order, no persisted gap
    holds a row that reached QuestDB or the WAL."""
    w, sink, store, _, clock = await make_writer(
        tmp_path_factory.mktemp("wal"), max_queue_rows=3, flush_rows=4
    )
    w.seed(SYMS)
    wal, gate = WalScript(w), Halt(w)
    gated: list[tuple[str, int]] = []
    admitted: dict[str, list[int]] = {sym: [] for sym in SYMS}
    for i, (kind, arg) in enumerate(steps, start=1):
        if kind == "trade":  # arg 3 / 4: a late row, older than the two before it
            sym, ts = SYMS[arg % 2], T0 + 10 * i - (35 if arg >= 3 else 0)
            (gated if gate.on else []).append((sym, ts))
            admitted[sym].append(ts)
            await w.on_trade(trade(i, sym, ts=ts))
        elif kind == "sink":
            sink.down = {"*"} if arg % 2 else set()
        elif kind == "gate":
            gate.on = bool(arg % 2)
        elif kind in ("pump", "recover"):  # `arg` caps this step's WAL appends (4 = no cap)
            wal.accept = None if arg == 4 else arg
            clock.advance(0.3)
            await (w.pump("trades") if kind == "pump" else w.recover())
        else:
            store.session = arg != 0
            await w.flush_gaps()
    store.session = True
    await w.flush_gaps()
    for sym, t in [*wal.refused, *gated]:
        assert any(
            g["symbol"] == sym and g["start"] <= _at(t) <= g["end"]  # type: ignore[operator]  # datetimes
            for g in store.gaps
        ), (sym, t)
    assert not w.pending_gaps() and not w._gate_gaps
    if any(ts != sorted(set(ts)) for ts in admitted.values()):
        return  # out of order: coverage only (a late row inside an open window is best-effort)
    written = {(str(r["symbol"]), int(str(r["ts"]))) for r in sink.rows("trades")}
    written |= set(wal.accepted)
    for gap in store.gaps:
        start, end = gap["start"], gap["end"]
        inside = [(s, t) for s, t in written if s == gap["symbol"] and start <= _at(t) < end]  # type: ignore[operator]  # datetimes
        assert not inside, (gap, inside)
