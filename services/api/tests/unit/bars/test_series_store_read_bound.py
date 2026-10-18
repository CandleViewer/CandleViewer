"""E12-T06 D2-G1 (#2787, #399): a process-wide bound on concurrent WS series tail reads (C-2.18).

At most `MAX_CONCURRENT_TAIL_READS` reads run at once across every `SeriesStore` on the loop. The
wait for a slot counts toward `timeout_s`, so a read that cannot start in time fails like any
timed-out read and its series is read again `retry_after_s` later. A slot is given back however
its read ends, and `bars_series_read_waits_total` counts the reads that had to wait for one.

Deterministic: the fake read blocks on events these tests set, the stores' clock is the test's,
and the loop is yielded to (`until`), never slept on; the wait counter is how a test knows a read
is waiting. No network, no QuestDB.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

import pytest

from candleviewer.bars import limits
from candleviewer.bars.limits import MAX_CONCURRENT_TAIL_READS as SLOTS
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import (
    MAX_HISTORY,
    MAX_SERIES,
    RETRY_AFTER_S,
    Hold,
    SeriesStore,
)
from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.unit.bars.test_series_store import (
    SPEC,
    SYM,
    Clock,
    H,
    bar,
    closes,
    counted,
    emit,
    up,
)

WAITS = "bars_series_read_waits_total"
FAILED = "bars_series_hydrate_failed_total"
LATE = "LATEUSDT"


def symbols(n: int, prefix: str = "S") -> list[str]:
    return [f"{prefix}{i:03d}USDT" for i in range(n)]


def waits() -> int:
    return int(counted(WAITS))


async def until(cond: Callable[[], bool], what: str) -> None:
    """Yield to the loop until `cond()` holds: a yield, not a delay. The count runs out only on a
    bug (a read that never starts, a wait that never ends), which fails the test, not hangs it."""
    for _ in range(1_000):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never reached: {what}")


async def finish(tasks: Sequence[asyncio.Task[Hold]]) -> None:
    """Every `ensure` ends without an error."""
    await until(lambda: all(t.done() for t in tasks), "every ensure ends")
    for t in tasks:
        t.result()


class Tails:
    """`TailRead` fake. A read of `symbol` blocks on `gate(symbol)`, then returns that symbol's
    bar 0, or raises `error`. `running` and `peak` count the reads in flight; `started` lists the
    symbols read, in the order their reads began."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.running = self.peak = 0
        self.error: Exception | None = None
        self._gates: dict[str, asyncio.Event] = {}
        self._open = False

    def gate(self, symbol: str) -> asyncio.Event:
        gate = self._gates.setdefault(symbol, asyncio.Event())
        if self._open:
            gate.set()
        return gate

    def open_all(self) -> None:
        """Let every read end, those in flight and those still to start."""
        self._open = True
        for gate in self._gates.values():
            gate.set()

    async def __call__(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        assert (spec, limit) == (SPEC, MAX_HISTORY)
        self.started.append(symbol)
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await self.gate(symbol).wait()
            if self.error is not None:
                raise self.error
            return BarTail([(0, bar(0, sym=symbol))])
        finally:
            self.running -= 1


def indexes(store: SeriesStore, symbol: str) -> list[int]:
    got = store.latest(symbol, H, MAX_HISTORY)
    assert got is not None
    return [b.index for b in got.closed]


def ensure_all(store: SeriesStore, names: Sequence[str]) -> list[asyncio.Task[Hold]]:
    return [asyncio.create_task(store.ensure(s, SPEC)) for s in names]


async def free_slots() -> int:
    """How many reads can start right now: one more than there are slots is offered on fresh
    series, and the reads that start are counted (the rest find every slot taken and wait). All of
    them end before it returns, so it leaves the slots as it found them."""
    tails, before = Tails(), waits()
    tasks = ensure_all(SeriesStore(tails, timeout_s=60.0), symbols(SLOTS + 1, "F"))
    await until(lambda: len(tails.started) + waits() - before == SLOTS + 1, "every read placed")
    free = len(tails.started)
    tails.open_all()
    await finish(tasks)
    return free


def test_the_read_bound_is_sixteen_reads() -> None:
    """A change is a reviewed diff (`bars/limits.py`), as for the other E12 numbers."""
    assert limits.MAX_CONCURRENT_TAIL_READS == 16


def test_the_wait_counter_is_one_unlabelled_live_catalogue_series() -> None:
    spec = next(s for s in CATALOGUE if s.name == WAITS)
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("counter", (), "live", True)


@pytest.mark.parametrize(
    "total", [SLOTS + 1, 2 * SLOTS, MAX_SERIES], ids=["n+1", "2n", "max-series"]
)
async def test_no_more_reads_than_slots_run_at_once_and_every_series_hydrates(total: int) -> None:
    tails, before = Tails(), waits()
    store = SeriesStore(tails, timeout_s=60.0)
    names = symbols(total)
    tasks = ensure_all(store, names)
    await until(
        lambda: len(tails.started) == SLOTS and waits() - before == total - SLOTS, "slots taken"
    )
    assert tails.running == SLOTS  # the rest wait, and none has started
    tails.gate(names[0]).set()  # one read ends: its slot goes to the first read that waited
    await until(lambda: len(tails.started) == SLOTS + 1, "a waiting read starts")
    assert tails.running == SLOTS and tails.started[-1] == names[SLOTS]
    tails.open_all()
    await finish(tasks)
    assert tails.peak == SLOTS and sorted(tails.started) == names  # each series read once
    assert all(store.hydrated(s, H) and indexes(store, s) == [0] for s in names)
    assert waits() - before == total - SLOTS
    assert await free_slots() == SLOTS


async def test_a_read_waiting_past_timeout_s_for_a_slot_fails_like_a_timed_out_read() -> None:
    """The wait counts toward `timeout_s` (SR-E12-01), so an `ensure` is held no longer than a
    slow read holds it; the series is read again `retry_after_s` later, like any failed read."""
    tails, clock = Tails(), Clock()
    blockers = ensure_all(SeriesStore(tails, timeout_s=60.0), symbols(SLOTS))
    await until(lambda: len(tails.started) == SLOTS, "every slot taken")
    store = SeriesStore(tails, timeout_s=0.0, clock=clock)  # another store: the bound is shared
    failed, before = counted(FAILED, "timeout"), waits()
    first = asyncio.create_task(store.ensure(LATE, SPEC))
    await until(first.done, "a wait outside timeout_s never ends")
    first.result()  # the failed read is no error: the series stays live-only
    assert (counted(FAILED, "timeout"), waits()) == (failed + 1, before + 1)
    assert LATE not in tails.started and not store.hydrated(LATE, H)
    clock.t += RETRY_AFTER_S - 0.5
    await store.ensure(LATE, SPEC)  # too soon: no read, so no wait for a slot either
    assert (counted(FAILED, "timeout"), waits()) == (failed + 1, before + 1)
    clock.t += 0.5  # `retry_after_s` after the failed read: it reads again, and fails again
    await store.ensure(LATE, SPEC)
    assert (counted(FAILED, "timeout"), waits()) == (failed + 2, before + 2)
    tails.open_all()
    await finish(blockers)
    clock.t += RETRY_AFTER_S  # the slots are free: a zero timeout lets a read that never waits end
    await store.ensure(LATE, SPEC)
    assert LATE in tails.started and store.hydrated(LATE, H)
    assert (counted(FAILED, "timeout"), waits()) == (failed + 2, before + 2)
    assert await free_slots() == SLOTS


async def test_a_slot_is_given_back_when_its_read_raises() -> None:
    tails = Tails()
    tails.error = OSError("questdb down")
    tails.open_all()
    failed = counted(FAILED, "connection")
    await SeriesStore(tails).ensure(SYM, SPEC)  # a failed read is no error: the series stays live
    assert counted(FAILED, "connection") == failed + 1
    assert await free_slots() == SLOTS


async def test_a_slot_is_given_back_when_its_read_times_out() -> None:
    tails, failed = Tails(), counted(FAILED, "timeout")  # the gate never opens: a hung read
    task = asyncio.create_task(SeriesStore(tails, timeout_s=0.0).ensure(SYM, SPEC))
    await until(task.done, "the hung read times out")
    task.result()
    assert tails.started == [SYM] and counted(FAILED, "timeout") == failed + 1
    assert tails.running == 0 and await free_slots() == SLOTS


async def test_a_cancelled_read_gives_its_slot_back_and_cancellation_propagates() -> None:
    tails = Tails()
    task = asyncio.create_task(SeriesStore(tails, timeout_s=60.0).ensure(SYM, SPEC))
    await until(lambda: tails.running == 1, "the read starts")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert tails.running == 0 and await free_slots() == SLOTS


async def test_a_read_cancelled_while_it_waits_for_a_slot_takes_none_and_returns_none() -> None:
    """Giving back a slot never taken would make room for a read beyond the bound."""
    tails, before = Tails(), waits()
    store = SeriesStore(tails, timeout_s=60.0)
    blockers = ensure_all(store, symbols(SLOTS))
    waiter = asyncio.create_task(store.ensure(LATE, SPEC))
    await until(lambda: len(tails.started) == SLOTS and waits() - before == 1, "one read waits")
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert LATE not in tails.started and tails.running == SLOTS
    tails.open_all()
    await finish(blockers)
    assert tails.peak == SLOTS and await free_slots() == SLOTS


async def test_the_wait_counter_moves_only_for_a_read_that_had_to_wait() -> None:
    tails, before = Tails(), waits()
    store = SeriesStore(tails, timeout_s=60.0)
    blockers = ensure_all(store, symbols(SLOTS))
    await until(lambda: len(tails.started) == SLOTS, "every slot taken")
    assert waits() == before  # a free slot is no wait: SLOTS reads, none waited
    waiter = asyncio.create_task(store.ensure(LATE, SPEC))
    await until(lambda: waits() == before + 1, "the one more read waits")
    tails.open_all()
    await finish([*blockers, waiter])
    await store.ensure("AFTERUSDT", SPEC)  # the slots are free again: no wait
    assert waits() == before + 1


async def test_the_bound_is_shared_by_every_store_in_the_process() -> None:
    tails, before = Tails(), waits()
    one, other = SeriesStore(tails, timeout_s=60.0), SeriesStore(tails, timeout_s=60.0)
    half = SLOTS // 2
    tasks = [*ensure_all(one, symbols(half, "A")), *ensure_all(other, symbols(SLOTS - half, "B"))]
    await until(lambda: len(tails.started) == SLOTS, "every slot taken")
    tasks.append(asyncio.create_task(one.ensure(LATE, SPEC)))  # `one` holds only half of them
    await until(lambda: waits() == before + 1, "the read beyond the bound waits")
    assert LATE not in tails.started
    tails.open_all()
    await finish(tasks)
    assert tails.peak == SLOTS and LATE in tails.started


async def test_a_series_waiting_for_a_slot_is_one_read_in_flight_that_keeps_its_closes() -> None:
    """The wait is part of the read: a second `ensure` of the series waits for that read (it takes
    no slot of its own), and a close amended meanwhile is folded over the rows the read takes."""
    tails, before = Tails(), waits()
    store = SeriesStore(tails, timeout_s=60.0)
    blockers = ensure_all(store, symbols(SLOTS))
    waiters = ensure_all(store, [SYM, SYM])
    await until(lambda: len(tails.started) == SLOTS and waits() - before == 1, "the series waits")
    await emit(store, up("close", 0, amended=True, close="105"))  # its row is not stored yet
    tails.open_all()
    await finish([*blockers, *waiters])
    assert tails.started.count(SYM) == 1 and waits() - before == 1
    assert closes(store) == [(0, "105")]


def test_the_bound_follows_the_running_loop() -> None:
    """A semaphore made earlier and contended on a second loop raises `RuntimeError`, which the
    store counts as a failed read: the bound is made on the loop that reads, so each loop (a
    test's, a restarted app's) has its own, and the read that waited is read, not failed."""

    async def contended() -> int:
        tails, names = Tails(), symbols(SLOTS + 1)
        store = SeriesStore(tails, timeout_s=60.0)
        tasks = ensure_all(store, names)
        await until(lambda: len(tails.started) == SLOTS, "every slot taken")
        tails.open_all()
        await finish(tasks)
        assert sorted(tails.started) == names and all(store.hydrated(s, H) for s in names)
        return tails.peak

    assert [asyncio.run(contended()), asyncio.run(contended())] == [SLOTS, SLOTS]
