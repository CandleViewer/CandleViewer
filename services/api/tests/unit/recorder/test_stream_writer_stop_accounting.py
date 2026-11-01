"""#5333: `stop()` cancelling a lane mid-step never loses a row without a count (C-2.18).

Every admitted row ends written, in the WAL (replayed on the next start) or counted as dropped
with a gap. Two lane steps used to break that when `stop()` cancelled them: a WAL append whose
thread outlived the cancelled await (its refused suffix was never dropped), and a flush whose
batch went back to the queue of a lane that had started to spill meanwhile (stranded there).
A third made `stop()` itself hang: a replay cancelled while its thread was inside the WAL merge.
The wait for such a thread is bounded (`wal_join_timeout_s`, or a second cancellation): a hung
thread then leaves its rows under a gap and the cancellation goes on.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from candleviewer.recorder.wal import WalRecord, read_frames
from candleviewer.recorder.writer import StreamWriter, _join_thread
from tests.unit.recorder._writer_helpers import T0, FakeSink, make_writer, trade

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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

    # mypy forbids assigning to a method; the test swaps the WAL's thread body for a slow one
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

    # mypy forbids assigning to a method; the test swaps the merge for one that blocks inside
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


async def test_stop_gives_up_on_a_hung_wal_append_and_covers_its_rows(tmp_path: Path) -> None:
    """A cancelled append whose thread never returns (a hung fsync) holds stop() for at most
    `wal_join_timeout_s`: its rows go under one gap, a critical event says so, stop() ends."""
    w, sink, store, events, clock = await make_writer(tmp_path, wal_join_timeout_s=0.05)
    lane = w._lanes["trades"]
    entered, release = threading.Event(), threading.Event()

    def hung_append(records: list[WalRecord]) -> int:
        entered.set()
        release.wait(30)  # never set while the test asserts: a thread that does not finish
        return len(records)

    # mypy forbids assigning to a method; the test swaps the WAL's thread body for a hung one
    lane.wal.append = hung_append  # type: ignore[method-assign]
    sink.down.add("*")
    for i in range(3):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    w._spawn(w.pump("trades"), "recorder-lane-trades")  # a lane step, owned as start() owns it
    try:
        await asyncio.to_thread(entered.wait, 5)
        async with asyncio.timeout(5):
            await w.stop()
        assert not w._tasks
        assert "recorder_wal_append_unresolved" in [e.kind for e in events.events]
        (gap,) = store.gaps  # one window over all three rows, persisted by stop()
        assert gap["start"] == _EPOCH + timedelta(microseconds=T0)  # rows 0..2 at T0+0..2
        end = gap["end"]
        assert isinstance(end, datetime) and end >= _EPOCH + timedelta(microseconds=T0 + 2)
        assert gap["cause"] == "backpressure_drop"
    finally:
        release.set()  # let the thread go, so the loop's executor can shut down


async def test_join_thread_stops_waiting_on_a_second_cancellation() -> None:
    never: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    join = asyncio.create_task(_join_thread(never, 60.0))
    await asyncio.sleep(0)
    join.cancel()
    await asyncio.sleep(0)
    join.cancel()
    joined = await join
    assert joined.cancelled is not None and joined.unresolved is joined.cancelled
    assert not never.done()
    never.cancel()


async def test_cancelled_append_that_fails_drops_every_row_with_a_gap(tmp_path: Path) -> None:
    """Any failure of a cancelled append (not only OSError) drops its rows with a count and a
    gap, and the cancellation goes on with the failure as its cause."""
    w, sink, store, _, clock = await make_writer(tmp_path)
    lane = w._lanes["trades"]
    entered, release = threading.Event(), threading.Event()

    def failing_append(records: list[WalRecord]) -> int:
        entered.set()
        release.wait(5)
        raise RuntimeError("wal broke")

    # mypy forbids assigning to a method; the test swaps the WAL's thread body for a failing one
    lane.wal.append = failing_append  # type: ignore[method-assign]
    sink.down.add("*")
    for i in range(3):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    step = asyncio.create_task(w.pump("trades"))
    await asyncio.to_thread(entered.wait, 5)
    step.cancel()
    await asyncio.sleep(0)
    release.set()
    try:
        await step
    except asyncio.CancelledError as exc:
        assert isinstance(exc.__cause__, RuntimeError)
    else:
        raise AssertionError("the cancellation was swallowed")
    await w.stop()
    assert _dropped(store.counters) == 3 and store.gaps


async def test_wal_step_cancelled_mid_thread_waits_for_it_then_cancels(tmp_path: Path) -> None:
    """m2: a WAL step (commit, begin_replay, ...) cancelled mid-thread is waited out, so the
    WAL and its budget never change behind the writer's back, and the cancellation goes on."""
    w, *_ = await make_writer(tmp_path)
    lane = w._lanes["trades"]
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def step_body() -> None:
        entered.set()
        release.wait(5)
        finished.set()

    call = asyncio.create_task(w._wal_call(lane, step_body))
    await asyncio.to_thread(entered.wait, 5)
    call.cancel()
    await asyncio.sleep(0)
    release.set()
    try:
        await call
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("the cancellation was swallowed")
    assert finished.is_set()  # the caller ended only after its thread did
