"""#5333: `stop()` cancelling a lane mid-step never loses a row without a count (C-2.18).

Every admitted row ends written, in the WAL (replayed on the next start) or counted as dropped
with a gap. Two lane steps used to break that when `stop()` cancelled them: a WAL append whose
thread outlived the cancelled await (its refused suffix was never dropped), and a flush whose
batch went back to the queue of a lane that had started to spill meanwhile (stranded there).
A third made `stop()` itself hang: a replay cancelled while its thread was inside the WAL merge.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator
from pathlib import Path

from candleviewer.recorder.wal import WalRecord, read_frames
from candleviewer.recorder.writer import StreamWriter
from tests.unit.recorder._writer_helpers import FakeSink, make_writer, trade


def _wal_rows(w: StreamWriter) -> int:
    path = w._lanes["trades"].wal.spill_path
    if not path.exists():
        return 0
    with path.open("rb") as fh:
        return sum(1 for _ in read_frames(fh))


def _dropped(store_counters: list[tuple[str, dict[str, int]]]) -> int:
    return sum(kw["messages_dropped"] for _, kw in store_counters)


async def test_stop_mid_wal_append_drops_the_refused_suffix_with_a_count(tmp_path: Path) -> None:
    w, sink, store, _, clock = await make_writer(tmp_path)
    lane = w._lanes["trades"]
    entered, release = threading.Event(), threading.Event()
    appended: list[WalRecord] = []

    def slow_append(records: list[WalRecord]) -> int:
        """The WAL takes the first record and refuses the rest (budget), after a slow fsync."""
        entered.set()
        release.wait(5)
        appended.extend(records[:1])
        return 1

    lane.wal.append = slow_append  # type: ignore[method-assign]
    sink.down.add("*")  # the flush fails: the lane spills its batch from inside the step
    for i in range(3):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    step = asyncio.create_task(w.pump("trades"))
    w._tasks.add(step)  # a lane loop's step, as `start()` would own it
    await asyncio.to_thread(entered.wait, 5)
    stopping = asyncio.create_task(w.stop())
    await asyncio.sleep(0)  # stop() cancels the step while its append thread still runs
    release.set()
    await stopping
    assert len(appended) == 1
    assert _dropped(store.counters) == 2  # 3 rows: 1 in the WAL + 2 dropped, none silent
    assert ("BTCUSDT", "trades") not in w.pending_gaps()  # the drop's gap was persisted
    assert store.gaps and store.gaps[0]["cause"] == "backpressure_drop"


class _GatedSink(FakeSink):
    """A sink whose write waits until the test lets it go (an ILP socket mid-send)."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.go = asyncio.Event()

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.entered.set()
        await self.go.wait()
        await super().write_rows(table, rows, ts_us_key)


async def test_stop_mid_flush_of_a_lane_that_began_to_spill_keeps_the_batch(
    tmp_path: Path,
) -> None:
    sink = _GatedSink()
    w, _, store, _, clock = await make_writer(tmp_path, sink=sink, max_queue_rows=3)
    for i in range(2):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    step = asyncio.create_task(w.pump("trades"))  # flushes rows 0-1, the sink holds them
    w._tasks.add(step)
    await sink.entered.wait()
    for i in range(2, 6):  # the queue overflows meanwhile: the lane spills rows 2-5
        await w.on_trade(trade(i))
    assert w.is_spilling("trades")
    await w.stop()  # cancels the flush mid-write
    written = len(sink.rows("trades"))
    assert written + _wal_rows(w) + _dropped(store.counters) == 6
    assert written == 0 and _wal_rows(w) == 6


async def test_stop_mid_replay_ends_the_lane_loop(tmp_path: Path) -> None:
    """A stop() that cancels a replay while its thread is inside the WAL merge iterator ends
    the lane loop. Closing the iterator under the thread raised ValueError, which the loop
    caught as a lane error and ran on: stop() then waited for it forever."""
    w, sink, _, _, clock = await make_writer(tmp_path, max_queue_rows=1)
    for i in range(3):
        await w.on_trade(trade(i))  # the queue bound spills them; the producer appends them
    assert _wal_rows(w) == 3
    lane = w._lanes["trades"]
    entered, release = threading.Event(), threading.Event()
    merge = lane.wal.iter_replay

    def slow_merge() -> Generator[tuple[int, WalRecord]]:
        for item in merge():
            entered.set()
            release.wait(5)
            yield item

    lane.wal.iter_replay = slow_merge  # type: ignore[method-assign]
    clock.advance(5.0)  # the replay is due
    w._spawn(w._lane_loop("trades"), "recorder-lane-trades")
    await asyncio.to_thread(entered.wait, 5)
    stopping = asyncio.create_task(w.stop())
    await asyncio.sleep(0)  # stop() cancels the loop while the merge thread holds the iterator
    release.set()
    async with asyncio.timeout(5):
        await stopping
    assert not w._tasks and lane.wal.has_data()  # the rows stay durable for the next start
    assert not sink.rows("trades")  # cancelled before its write: replayed next start
