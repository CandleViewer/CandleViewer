"""#2223: the periodic book seek anchor (24-internal-schemas.md §13.7).

The anchors go through the real `StreamWriter` lane (queue -> `_write`) into a `FakeSink`; the
clocks are fakes, nothing sleeps, nothing leaves `tmp_path`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from structlog.testing import capture_logs

from candleviewer.book.resync import BookEngine
from candleviewer.exchange.base.models import BookSnapshot
from candleviewer.recorder.metrics import recorder_anchor_skipped_total
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.snapshot_anchors import (
    STAMP_MARGIN_US,
    NoAnchor,
    SnapshotAnchors,
    anchor_ts,
)
from candleviewer.recorder.writer import DiskGate, StreamWriter
from candleviewer.settings import Settings
from tests.unit.book._builders import delta as book_delta
from tests.unit.book._builders import lvl
from tests.unit.book._builders import snap as book_snap
from tests.unit.recorder._writer_helpers import (
    T0,
    FakeClock,
    FakeSink,
    FakeStore,
    delta,
    make_writer,
    snapshot,
)

INTERVAL = 60.0
S = 1_000_000


class FakeBooks:
    """`AnchorBooks`: per symbol, the book to anchor or the reason there is none."""

    def __init__(self) -> None:
        self.books: dict[str, BookSnapshot | NoAnchor] = {}
        self.raises: set[str] = set()

    def anchor(self, symbol: str) -> BookSnapshot | NoAnchor:
        if symbol in self.raises:
            raise RuntimeError("book adapter bug")
        return self.books.get(symbol, "no_book")


def skipped(reason: str) -> float:
    return float(recorder_anchor_skipped_total.labels(reason=reason)._value.get())


def added(symbol: str) -> RecorderSetChanged:
    return RecorderSetChanged(
        symbol=symbol, change="added", reason="manual", reasons=("manual",), priority=1,
        auto_evictable=False, ts_event=T0,
    )  # fmt: skip


def wall(clock: FakeClock) -> int:
    """The writer's wall clock in µs (as `make_writer` wires it)."""
    return T0 + int(clock.t * S)


async def rig(
    tmp_path: Path,
) -> tuple[SnapshotAnchors, FakeBooks, StreamWriter, FakeSink, FakeStore, FakeClock]:
    writer, sink, store, _events, clock = await make_writer(tmp_path)
    books = FakeBooks()
    anchors = SnapshotAnchors(
        books, writer, interval_s=INTERVAL, clock=clock, wall_us=lambda: wall(clock)
    )
    return anchors, books, writer, sink, store, clock


async def flushed_anchors(writer: StreamWriter, sink: FakeSink) -> list[dict[str, object]]:
    await writer.pump("orderbook_snapshots")  # the lane's own flush: the delta path
    return sink.rows("orderbook_snapshots")


# --- the stamp ---------------------------------------------------------------------------------


def test_anchor_ts_of_a_busy_book_is_just_after_its_last_applied_event() -> None:
    last = T0 + 7_000  # an exchange stamp: whole milliseconds
    assert anchor_ts(last, last + 100_000) == last + 1


def test_anchor_ts_of_a_quiet_book_is_the_slot_less_the_margin_never_on_a_millisecond() -> None:
    slot = T0 + 3_600 * S
    assert anchor_ts(T0, slot) == slot - STAMP_MARGIN_US + 1  # T0 is whole ms: moved off it
    assert anchor_ts(T0, slot + 7) == slot + 7 - STAMP_MARGIN_US


def test_anchor_ts_is_always_after_the_last_applied_event() -> None:
    last = T0 + 50 * S
    assert anchor_ts(last, last - 10 * S) == last + 1  # a local clock behind the exchange's


# --- cadence -----------------------------------------------------------------------------------


async def test_snapshot_anchors_first_tick_anchors_a_live_book_at_once_then_on_the_grid(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(7)

    await anchors.tick()  # arms the grid and anchors the new LIVE book (F8)
    for _ in range(int(INTERVAL) - 1):
        clock.advance(1)
        await anchors.tick()
    assert len(await flushed_anchors(writer, sink)) == 1
    clock.advance(1)
    await anchors.tick()
    clock.advance(1)

    assert len(await flushed_anchors(writer, sink)) == 2


async def test_snapshot_anchors_a_book_going_live_mid_interval_is_anchored_without_a_skip(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = "not_live"
    before = skipped("not_live")

    await anchors.tick()
    for _ in range(10):  # not due: an unanchored book is retried quietly every tick
        clock.advance(1)
        await anchors.tick()
    books.books["BTCUSDT"] = snapshot(7)
    clock.advance(1)
    await anchors.tick()
    clock.advance(1)

    assert skipped("not_live") == before
    assert len(await flushed_anchors(writer, sink)) == 1


async def test_snapshot_anchors_due_tick_writes_a_synthetic_row_through_the_writer_lane(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(7)
    await anchors.tick()
    clock.advance(INTERVAL)
    slot = wall(clock)
    await anchors.tick()
    clock.advance(1)

    row = (await flushed_anchors(writer, sink))[-1]
    assert (row["symbol"], row["update_id"], row["depth"], row["level_count"]) == (
        "BTCUSDT", 7, 200, 3,
    )  # fmt: skip
    assert row["source"] == "synthetic" and row["ts"] == anchor_ts(T0 + 7, slot)


async def test_snapshot_anchors_a_live_book_idle_for_30_s_is_anchored_after_its_last_event(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    last = wall(clock) - 30 * S  # Bybit sends nothing while the book does not change
    books.books["BTCUSDT"] = snapshot(5).model_copy(update={"ts_event": last})

    await anchors.tick()
    clock.advance(1)

    (row,) = await flushed_anchors(writer, sink)
    assert last < cast(int, row["ts"]) <= wall(clock)
    assert row["update_id"] == 5  # the book is unchanged since: valid at the slot


async def test_snapshot_anchors_one_anchor_per_interval_for_each_recorded_symbol_only(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    writer.on_set_changed(added("ETHUSDT"))
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):  # SOLUSDT has a book but is not recorded
        books.books[symbol] = snapshot(3, symbol=symbol)

    await anchors.tick()
    for _ in range(3):  # three intervals, ticked once a second as the runtime does
        for _ in range(int(INTERVAL)):
            clock.advance(1)
            await anchors.tick()
    clock.advance(1)

    rows = await flushed_anchors(writer, sink)
    assert sorted(str(r["symbol"]) for r in rows) == ["BTCUSDT"] * 4 + ["ETHUSDT"] * 4


async def test_snapshot_anchors_a_late_tick_anchors_once_and_counts_the_missed_slots(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(9)
    before = skipped("late")

    await anchors.tick()  # the first anchor
    clock.advance(3 * INTERVAL + 5)  # the loop stalled through two whole slots
    await anchors.tick()
    clock.advance(INTERVAL - 6)  # the grid holds: the next slot is 4 intervals after arming
    await anchors.tick()
    clock.advance(1)

    assert len(await flushed_anchors(writer, sink)) == 2
    assert skipped("late") == before + 2
    await anchors.tick()
    clock.advance(1)
    assert len(await flushed_anchors(writer, sink)) == 3


# --- skips ------------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["no_book", "not_live"])
async def test_snapshot_anchors_skipped_book_counts_the_reason_and_writes_no_gap_row(
    tmp_path: Path, reason: str
) -> None:
    anchors, books, writer, sink, store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = cast(NoAnchor, reason)
    before = skipped(reason)

    await anchors.tick()
    clock.advance(INTERVAL)
    with capture_logs() as logs:
        await anchors.tick()
    clock.advance(1)
    await writer.flush_gaps()

    assert skipped(reason) == before + 1
    assert [(e["event"], e["symbol"], e["reason"]) for e in logs] == [
        ("recorder_anchor_skipped", "BTCUSDT", reason)
    ]
    assert await flushed_anchors(writer, sink) == []
    assert store.gaps == []  # no data is lost: the deltas are still recorded (§13.7)


async def test_snapshot_anchors_a_raising_book_source_is_an_error_skip_and_others_still_anchor(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, store, clock = await rig(tmp_path)
    writer.on_set_changed(added("ETHUSDT"))
    books.raises.add("BTCUSDT")
    await anchors.tick()
    books.books["ETHUSDT"] = snapshot(5, symbol="ETHUSDT")
    before = skipped("error")

    clock.advance(INTERVAL)
    with capture_logs() as logs:
        await anchors.tick()
    clock.advance(1)

    assert skipped("error") == before + 1
    assert [e.get("error") for e in logs if e["event"] == "recorder_anchor_skipped"] == [
        "RuntimeError"
    ]
    assert [r["symbol"] for r in await flushed_anchors(writer, sink)] == ["ETHUSDT"]
    assert store.gaps == []


async def test_snapshot_anchors_a_failing_writer_admit_is_an_error_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchors, books, writer, _sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(1)

    async def broken(_ev: object, *, at_us: int) -> None:
        raise OSError("wal unwritable")

    monkeypatch.setattr(writer, "on_book_anchor", broken)  # the sink's one failure mode
    before = skipped("error")
    await anchors.tick()
    clock.advance(INTERVAL)
    await anchors.tick()

    assert skipped("error") == before + 1  # the slot's: between slots it is only retried


async def test_snapshot_anchors_a_slot_cut_by_the_step_timeout_counts_the_rest_as_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    for symbol in ("ETHUSDT", "SOLUSDT"):
        writer.on_set_changed(added(symbol))
    await anchors.tick()  # no book yet: nothing anchored, the grid is armed
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        books.books[symbol] = snapshot(4, symbol=symbol)
    real, entered = writer.on_book_anchor, asyncio.Event()

    async def hang_on_eth(ev: BookSnapshot, *, at_us: int) -> str | None:
        if ev.symbol == "ETHUSDT":
            entered.set()
            await asyncio.Event().wait()  # until the runtime's step timeout cancels the tick
        return await real(ev, at_us=at_us)

    monkeypatch.setattr(writer, "on_book_anchor", hang_on_eth)
    before = skipped("timeout")
    clock.advance(INTERVAL)
    step = asyncio.create_task(anchors.tick())
    await entered.wait()
    step.cancel()
    with pytest.raises(asyncio.CancelledError):
        await step
    clock.advance(1)

    assert skipped("timeout") == before + 2  # ETHUSDT (cut) and SOLUSDT (never reached)
    assert [r["symbol"] for r in await flushed_anchors(writer, sink)] == ["BTCUSDT"]


@pytest.mark.parametrize("interval", [0.0, -1.0, float("inf"), float("nan")])
def test_snapshot_anchors_refuse_an_interval_that_is_not_positive_and_finite(
    interval: float,
) -> None:
    with pytest.raises(ValueError, match="interval_s"):
        SnapshotAnchors(
            FakeBooks(), cast(StreamWriter, object()), interval_s=interval, clock=lambda: 0.0,
            wall_us=lambda: 0,
        )  # fmt: skip


# --- the writer keeps anchors out of the delta accounting ----------------------------------------


async def test_writer_anchor_never_moves_the_delta_sequence_tracker(tmp_path: Path) -> None:
    """The bus may still hold deltas older than the book the anchor was read from: an anchor
    that moved the tracker would turn the next of them into a false `seq_jump`."""
    writer, _sink, _store, _events, _clock = await make_writer(tmp_path)
    await writer.on_book_delta(delta(5))
    await writer.on_book_anchor(snapshot(9), at_us=T0 + 10)
    await writer.on_book_delta(delta(6))

    assert list(writer.seq_jumps) == []


async def test_writer_anchor_is_neither_received_nor_in_the_event_bounds(tmp_path: Path) -> None:
    writer, _sink, store, _events, clock = await make_writer(tmp_path)
    assert await writer.on_book_anchor(snapshot(9), at_us=T0 + 10) is None
    await writer.on_book_anchor(snapshot(10, symbol="SOLUSDT"), at_us=T0 + 11)  # not recorded
    clock.advance(1)
    await writer.pump("orderbook_snapshots")
    await writer.flush_counters()

    assert [kw["messages_received"] for _s, kw in store.counters] == [0]
    assert writer.recorded() == frozenset({"BTCUSDT"})
    assert writer.take_event_bounds() == {}  # an anchor is not a recorded market event


async def test_writer_sheds_an_anchor_while_its_lane_spills(tmp_path: Path) -> None:
    """Anchors never spend the WAL budget the deltas need."""
    writer, sink, _store, _events, clock = await make_writer(tmp_path)
    sink.down.add("orderbook_snapshots")
    await writer.on_book_snapshot(snapshot(1))
    clock.advance(1)
    await writer.pump("orderbook_snapshots")  # the flush fails: the lane spills
    assert writer.is_spilling("orderbook_snapshots")
    spilled = writer.spill_bytes

    assert await writer.on_book_anchor(snapshot(2), at_us=T0 + 3) == "spilling"
    await writer.pump("orderbook_snapshots")
    assert writer.spill_bytes == spilled


async def test_writer_sheds_an_anchor_that_would_start_a_spill(tmp_path: Path) -> None:
    writer, _sink, _store, _events, _clock = await make_writer(tmp_path, max_queue_rows=1)
    await writer.on_book_snapshot(snapshot(1))
    assert await writer.on_book_anchor(snapshot(2), at_us=T0 + 3) == "spilling"
    assert not writer.is_spilling("orderbook_snapshots")


async def test_writer_gated_anchor_is_shed_without_a_drop_or_a_gate_gap(tmp_path: Path) -> None:
    writer, _sink, store, _events, clock = await make_writer(tmp_path)
    writer._gate = DiskGate(halted=lambda: True, position_open=lambda _s: False)

    assert await writer.on_book_anchor(snapshot(2), at_us=T0 + 3) == "gated"
    clock.advance(1)
    await writer.flush_gaps()
    await writer.flush_counters()

    assert store.gaps == [] and store.counters == []


async def test_writer_an_anchor_dropped_by_a_full_wal_is_no_dropped_message_and_no_gap(
    tmp_path: Path,
) -> None:
    writer, sink, store, _events, clock = await make_writer(tmp_path, wal_max_bytes=1 << 20)
    writer._budget.used = writer._budget.max_bytes  # the shared WAL budget is spent
    before = skipped("spilling")
    assert await writer.on_book_anchor(snapshot(2), at_us=T0 + 3) is None  # queued
    sink.down.add("orderbook_snapshots")
    clock.advance(1)
    await writer.pump("orderbook_snapshots")  # the flush fails, the WAL refuses: dropped
    await writer.flush_gaps()
    await writer.flush_counters()

    assert skipped("spilling") == before + 1
    assert store.gaps == []
    assert [kw["messages_dropped"] for _s, kw in store.counters] in ([], [0])


# --- the real engine -----------------------------------------------------------------------------


class _EngineBooks:
    def __init__(self, engine: BookEngine) -> None:
        self.engine = engine

    def anchor(self, symbol: str) -> BookSnapshot | NoAnchor:
        snap = self.engine.anchor_snapshot()
        return "not_live" if snap is None else snap


async def _nothing() -> None:
    """A resubscribe that does nothing."""


async def _drop(_obj: object) -> None:
    """A publish that drops."""


async def test_snapshot_anchors_across_a_delta_burst_through_the_real_engine(
    tmp_path: Path,
) -> None:
    writer, sink, _store, _events, clock = await make_writer(tmp_path)
    engine = BookEngine(
        symbol="BTCUSDT", depth=200, publish=_drop, resubscribe=_nothing, now_us=lambda: 0
    )  # fmt: skip
    anchors = SnapshotAnchors(
        _EngineBooks(engine), writer, interval_s=INTERVAL, clock=clock, wall_us=lambda: wall(clock)
    )
    await engine.start()
    base = wall(clock) - 2 * S  # the burst ends just before the tick, in whole ms
    await engine.on_event(book_snap(1, [lvl(99, 1)], [lvl(101, 1)]).model_copy(
        update={"ts_event": base}))  # fmt: skip
    for u in range(2, 12):  # ten deltas, 10 ms apart
        d = book_delta(u, u - 1, [lvl(99, u)])
        await engine.on_event(d.model_copy(update={"ts_event": base + (u - 1) * 10_000}))

    await anchors.tick()
    clock.advance(1)

    (row,) = await flushed_anchors(writer, sink)
    assert row["update_id"] == 11 and row["ts"] == base + 10 * 10_000 + 1


def test_settings_snapshot_interval_defaults_to_60_s_and_refuses_zero() -> None:
    assert Settings().recorder_snapshot_interval_s == 60
    with pytest.raises(ValueError, match="recorder_snapshot_interval_s"):
        Settings(recorder_snapshot_interval_s=0)
