"""#2223: the periodic book seek anchor (24-internal-schemas.md §13.7).

The anchors go through the real `StreamWriter` lane (`_admit` -> queue -> `_write`, or the WAL
when spilling) into a `FakeSink`; the clock is a fake, nothing sleeps, nothing leaves `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.models import BookSnapshot
from candleviewer.recorder.metrics import recorder_anchor_skipped_total
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.snapshot_anchors import NoAnchor, SnapshotAnchors
from candleviewer.recorder.writer import StreamWriter
from candleviewer.settings import Settings
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


async def rig(
    tmp_path: Path,
) -> tuple[SnapshotAnchors, FakeBooks, StreamWriter, FakeSink, FakeStore, FakeClock]:
    writer, sink, store, _events, clock = await make_writer(tmp_path)
    books = FakeBooks()
    anchors = SnapshotAnchors(books, writer, interval_s=INTERVAL, clock=clock)
    return anchors, books, writer, sink, store, clock


async def flushed_anchors(writer: StreamWriter, sink: FakeSink) -> list[dict[str, object]]:
    await writer.pump("orderbook_snapshots")  # the lane's own flush: the delta path
    return sink.rows("orderbook_snapshots")


async def test_snapshot_anchors_before_the_first_interval_writes_nothing(tmp_path: Path) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(7)

    await anchors.tick()  # arms the grid
    clock.advance(INTERVAL - 1)
    await anchors.tick()
    clock.advance(1)  # past the flush interval too: anything queued would go out

    assert await flushed_anchors(writer, sink) == []


async def test_snapshot_anchors_due_tick_writes_the_book_through_the_writer_lane(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(7)

    await anchors.tick()
    clock.advance(INTERVAL)
    await anchors.tick()
    clock.advance(1)

    rows = await flushed_anchors(writer, sink)
    assert [(r["ts"], r["symbol"], r["update_id"], r["depth"], r["level_count"]) for r in rows] == [
        (T0 + 7, "BTCUSDT", 7, 200, 3)
    ]


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
    assert sorted(str(r["symbol"]) for r in rows) == ["BTCUSDT"] * 3 + ["ETHUSDT"] * 3


@pytest.mark.parametrize("reason", ["no_book", "not_live", "stale"])
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
    books.books["ETHUSDT"] = snapshot(5, symbol="ETHUSDT")
    books.raises.add("BTCUSDT")
    before = skipped("error")

    await anchors.tick()
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


async def test_snapshot_anchors_a_late_tick_anchors_once_and_counts_the_missed_slots(
    tmp_path: Path,
) -> None:
    anchors, books, writer, sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(9)
    before = skipped("late")

    await anchors.tick()
    clock.advance(3 * INTERVAL + 5)  # the loop stalled through two whole slots
    await anchors.tick()
    clock.advance(INTERVAL - 6)  # the grid holds: the next slot is 4 intervals after arming
    await anchors.tick()
    clock.advance(1)

    assert len(await flushed_anchors(writer, sink)) == 1
    assert skipped("late") == before + 2
    await anchors.tick()
    clock.advance(1)
    assert len(await flushed_anchors(writer, sink)) == 2


async def test_snapshot_anchors_a_failing_writer_admit_is_an_error_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchors, books, writer, _sink, _store, clock = await rig(tmp_path)
    books.books["BTCUSDT"] = snapshot(1)

    async def broken(_ev: object) -> None:
        raise OSError("wal unwritable")

    monkeypatch.setattr(writer, "on_book_anchor", broken)  # the sink's one failure mode
    before = skipped("error")
    await anchors.tick()
    clock.advance(INTERVAL)
    await anchors.tick()

    assert skipped("error") == before + 1


@pytest.mark.parametrize("interval", [0.0, -1.0, float("inf"), float("nan")])
def test_snapshot_anchors_refuse_an_interval_that_is_not_positive_and_finite(
    interval: float,
) -> None:
    with pytest.raises(ValueError, match="interval_s"):
        SnapshotAnchors(FakeBooks(), object(), interval_s=interval, clock=lambda: 0.0)  # type: ignore[arg-type]  # never called


async def test_writer_anchor_never_moves_the_delta_sequence_tracker(tmp_path: Path) -> None:
    """The bus may still hold deltas older than the book the anchor was read from: an anchor
    that moved the tracker would turn the next of them into a false `seq_jump`."""
    writer, _sink, _store, _events, _clock = await make_writer(tmp_path)
    await writer.on_book_delta(delta(5))
    await writer.on_book_anchor(snapshot(9))
    await writer.on_book_delta(delta(6))

    assert list(writer.seq_jumps) == []


async def test_writer_anchor_is_not_counted_as_a_received_message(tmp_path: Path) -> None:
    writer, _sink, store, _events, clock = await make_writer(tmp_path)
    await writer.on_book_anchor(snapshot(9))
    await writer.on_book_anchor(snapshot(10, symbol="SOLUSDT"))  # not recorded: ignored
    clock.advance(1)
    await writer.pump("orderbook_snapshots")
    await writer.flush_counters()

    assert [kw["messages_received"] for _s, kw in store.counters] == [0]
    assert writer.recorded() == frozenset({"BTCUSDT"})


def test_settings_snapshot_interval_defaults_to_60_s_and_refuses_zero() -> None:
    assert Settings().recorder_snapshot_interval_s == 60
    with pytest.raises(ValueError, match="recorder_snapshot_interval_s"):
        Settings(recorder_snapshot_interval_s=0)
