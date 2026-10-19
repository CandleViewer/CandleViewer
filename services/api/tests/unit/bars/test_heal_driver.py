"""E12-T06 #2787 D2-H1 (P4b): the bars heal driver (`bars/heal_driver.py`) and the store's miss
streak it relies on (`bars/series_store.py`). The store's clock is the test's, reads are fakes and
the driver's `sleep` waits for the test to run each tick, so nothing sleeps; the timeout test runs
its own loop, whose timers keep the test's clock. No network, no QuestDB."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.bars.heal_driver import CONCURRENCY, INTERVAL_S, HealDriver
from candleviewer.bars.leases import CAP_GLOBAL
from candleviewer.bars.limits import HEAL_REFRESH_MARGIN_S, MAX_CONCURRENT_TAIL_READS
from candleviewer.bars.metrics import EXPORTED_NAMES
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import MAX_GAP_BACKOFF, RETRY_AFTER_S, Hold, SeriesStore
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.questdb.wiring import LazyPgWire
from tests.unit.bars.test_series_store import SPEC, SYM, Clock, H, Tail, counted, emit, rows, up
from tests.unit.bars.test_series_store_read_bound import symbols, until

REFRESHES, FAILED = "bars_heal_refresh_total", "bars_series_hydrate_failed_total"
RESULTS = ("repaired", "unchanged", "timeout", "error", "tick_error")


def refreshed() -> dict[str, float]:
    return {r: REGISTRY.get_sample_value(REFRESHES, {"result": r}) or 0.0 for r in RESULTS}


def since(before: dict[str, float]) -> dict[str, float]:
    """The refreshes counted since `before`, by result, the zeros left out."""
    return {r: n - before[r] for r, n in refreshed().items() if n != before[r]}


class Ticks:
    """The driver's `sleep`: each waits for the test to start a tick (`go`) or run one (`step`)."""

    def __init__(self) -> None:
        self.asked: list[float] = []
        self.sleeping, self._go = False, asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.asked.append(seconds)
        self.sleeping = True
        await self._go.wait()
        self._go.clear()

    async def go(self) -> None:
        await until(lambda: self.sleeping, "the driver sleeps")
        self.sleeping = False
        self._go.set()

    async def step(self) -> None:
        await self.go()
        await until(lambda: self.sleeping, "the tick ends")


Run = Callable[[SeriesStore], tuple[HealDriver, Ticks]]


@pytest.fixture
async def run() -> AsyncIterator[Run]:
    """Start a driver on a store, its ticks run by hand; each one is stopped at teardown."""
    made: list[HealDriver] = []

    def start(store: SeriesStore) -> tuple[HealDriver, Ticks]:
        ticks = Ticks()
        made.append(HealDriver(store, sleep=ticks))
        made[-1].start()
        return made[-1], ticks

    yield start
    for driver in made:
        await driver.stop()


async def failed_once() -> tuple[Clock, SeriesStore, Tail, Hold]:
    """A held series whose first read failed: due `retry_after_s` later; the reader is back."""
    clock, tail = Clock(), Tail(error=OSError("questdb down"), now=True)
    store = SeriesStore(tail, clock=clock)
    hold = await store.ensure(SYM, SPEC)
    tail.error = None
    return clock, store, tail, hold


class Reads:
    """`TailRead` fake: every read waits on one gate and withholds a row (SR-E12-11) while
    `dropped`; counts the reads in flight and their peak."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.running = self.peak = 0
        self.gate, self.dropped = asyncio.Event(), 1

    async def __call__(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        self.started.append(symbol)
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await self.gate.wait()
            return BarTail(rows(0), dropped=self.dropped)
        finally:
            self.running -= 1


async def test_a_tick_refreshes_at_most_4_due_series_at_once_the_earliest_due_first() -> None:
    """Ten held series whose first reads withheld a row, a second apart, are all due: a tick reads
    the four read first, together, and no more at once (half the read slots), then ends."""
    clock, reads = Clock(), Reads()
    store, names = SeriesStore(reads, clock=clock), symbols(10)
    reads.gate.set()
    holds = []
    for name in names:
        holds.append(await store.ensure(name, SPEC))
        clock.t += 1
    reads.gate.clear()
    reads.started, reads.peak, reads.dropped = [], 0, 0
    clock.t += RETRY_AFTER_S
    tick = asyncio.create_task(HealDriver(store).tick())
    await until(lambda: reads.running == CONCURRENCY, "four reads in flight")
    for _ in range(20):
        await asyncio.sleep(0)  # a yield, not a delay: no fifth read starts
    assert (reads.started, CONCURRENCY) == (names[:4], MAX_CONCURRENT_TAIL_READS // 2)
    reads.gate.set()
    await tick
    assert reads.peak == CONCURRENCY and len(holds) == len(names)
    assert [store.hydrated(n, H) for n in names] == [True] * 4 + [False] * 6


async def test_the_driver_reads_a_series_no_sooner_than_its_re_read_interval(run: Run) -> None:
    """A gapped series read at t is neither read nor tried by the ticks before t + 5 s; the tick
    at it reads the series and heals it."""
    clock, tail = Clock(), Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    _held = await store.ensure(SYM, SPEC)
    await emit(store, up("close", 11))  # a hole at 10
    tail.tail, before = BarTail(rows(*range(12))), refreshed()
    _driver, ticks = run(store)
    for _ in range(4):
        clock.t += INTERVAL_S
        await ticks.step()
    assert (tail.calls, since(before)) == (1, {})
    clock.t += INTERVAL_S
    await ticks.step()
    assert (tail.calls, store.gapped(SYM, H), since(before)) == (2, False, {"repaired": 1})
    assert set(ticks.asked) == {INTERVAL_S}


@pytest.mark.parametrize("fault", ["refresh", "cancelled", "due"])
async def test_refreshes_or_ticks_that_raise_count_each_log_a_streak_once_and_the_loop_goes_on(
    fault: str, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh that raises counts `error` (a stray cancellation too: its tick still waits for the
    rest), a `due` that raises `tick_error`. Two in a row log once; the next tick reads the series
    (it withholds a row, so it is due again), and the next fault logs again."""
    clock, store, tail, _held = await failed_once()
    tail.tail = BarTail([], dropped=1)
    name, faults = ("due" if fault == "due" else "refresh"), [True, True, False, True]
    real = getattr(store, name)

    def broken(*args: object, **kwargs: object) -> object:
        if not faults.pop(0):
            return real(*args, **kwargs)
        raise asyncio.CancelledError if fault == "cancelled" else RuntimeError("a broken store")

    monkeypatch.setattr(store, name, broken)
    before = refreshed()
    _driver, ticks = run(store)
    with capture_logs() as logs:
        clock.t += RETRY_AFTER_S
        for _ in range(3):
            await ticks.step()
        clock.t += 2 * RETRY_AFTER_S  # a second miss: 10 s
        await ticks.step()
    event = "bars_heal_tick_failed" if fault == "due" else "bars_heal_refresh_failed"
    error = "CancelledError" if fault == "cancelled" else "RuntimeError"
    assert [(e["event"], e["error_type"]) for e in logs] == [(event, error)] * 2
    assert since(before) == {"tick_error" if fault == "due" else "error": 3, "unchanged": 1}
    assert tail.calls == 2


async def test_the_fault_streaks_kept_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Past `CAP_GLOBAL` failing series it forgets their streaks (C-2.18): an old one logs again."""
    store = SeriesStore()
    driver, keys = HealDriver(store), [(f"S{i}", H) for i in range(CAP_GLOBAL + 1)]
    monkeypatch.setattr(store, "refresh", lambda *_: 1 / 0)  # every refresh raises
    with capture_logs() as logs:
        for due in (keys[:-1], keys[-1:] + keys[:1]):
            monkeypatch.setattr(store, "due", lambda *_, due=due, **__: due)
            await driver.tick()
    assert len(logs) == CAP_GLOBAL + 2  # each once, then the newest and the forgotten first


async def test_stop_ends_the_refresh_in_flight_and_leaves_no_task(run: Run) -> None:
    """`stop` cancels the task while a refresh reads: the read is cancelled (it counts and logs
    nothing, and sets no next read time) and every task the driver made has ended."""
    clock, store, tail, _held = await failed_once()
    tail.gate.clear()
    tail.started.clear()
    tasks, before = asyncio.all_tasks(), refreshed()
    driver, ticks = run(store)
    clock.t += RETRY_AFTER_S
    await ticks.go()
    await asyncio.wait_for(tail.started.wait(), 1.0)  # bounds, not delays
    assert [t.get_name() for t in asyncio.all_tasks() - tasks].count("bars-heal-driver") == 1
    with capture_logs() as logs:
        await asyncio.wait_for(driver.stop(), 1.0)
    assert (asyncio.all_tasks(), since(before), logs) == (tasks, {}, [])
    assert store.due(clock.t) == [(SYM, H)]  # it unwound before its deadline: no next read time


async def test_start_and_stop_twice_make_one_task_each_and_leave_none() -> None:
    """Each `start` makes the one task (a second call while it runs makes none) and each `stop`
    ends it, with nothing logged."""
    driver, tasks = HealDriver(SeriesStore(), sleep=Ticks()), asyncio.all_tasks()
    with capture_logs() as logs:
        for _ in range(2):
            driver.start()
            driver.start()
            assert [t.get_name() for t in asyncio.all_tasks() - tasks] == ["bars-heal-driver"]
            await driver.stop()
            assert asyncio.all_tasks() == tasks
    assert logs == []


@pytest.mark.parametrize(
    "end", [RuntimeError("a broken sleep"), asyncio.CancelledError()], ids=["raised", "cancelled"]
)
async def test_a_driver_task_ending_other_than_through_stop_is_logged(end: BaseException) -> None:
    """The task raised, or a cancellation `stop` did not make ended it: its done-callback logs."""

    async def sleep(_: float) -> None:
        raise end

    driver, event = HealDriver(SeriesStore(), sleep=sleep), "bars_heal_driver_ended"
    with capture_logs() as logs:
        driver.start()
        await until(lambda: bool(logs), "the end is logged")
        await driver.stop()
    assert [(e["event"], e["error_type"]) for e in logs] == [(event, type(end).__name__)]


async def test_stop_passes_on_a_cancellation_of_its_own_caller(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The teardown awaiting `stop` is cancelled while a refresh still unwinds: the cancellation
    reaches the teardown, and the driver's task ends anyway."""
    clock, store, _, _held = await failed_once()
    started, unwinding = asyncio.Event(), asyncio.Event()

    async def slow(symbol: str, spec_hash: str) -> bool:
        started.set()
        try:
            await asyncio.Event().wait()  # until `stop` cancels it
        finally:
            unwinding.set()
            await asyncio.Event().wait()  # until cancelled again
        return False

    monkeypatch.setattr(store, "refresh", slow)
    driver, ticks = run(store)
    clock.t += RETRY_AFTER_S
    await ticks.go()
    await asyncio.wait_for(started.wait(), 1.0)  # bounds, not delays
    stopper = asyncio.create_task(driver.stop())
    await asyncio.wait_for(unwinding.wait(), 1.0)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stopper, 1.0)
    assert "bars-heal-driver" not in {t.get_name() for t in asyncio.all_tasks()}


@pytest.mark.parametrize(
    ("hung", "unwind", "result"),
    [("read", 0, "unchanged"), ("read", 2.5, "unchanged"), ("read", 10, "timeout"),
     ("refresh", 0, "timeout")],
    ids=["read", "read-unwinds", "read-unwinds-past-the-bound", "refresh"],
)  # fmt: skip
def test_a_hung_read_ends_on_the_store_timeout_and_a_hung_refresh_on_the_driver_bound(
    hung: str, unwind: float, result: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that hangs is cut at the store's `timeout_s` and ends, once its reader has unwound
    (2.5 times `timeout_s` here, as `LazyPgWire`'s graceful close can), as a failed read with its
    next read time set (`unchanged`). A read whose unwind outlasts the driver's bound (`timeout_s`
    and `HEAL_REFRESH_MARGIN_S`) is cut there (`timeout`, logged), a failed read all the same; a
    refresh that hangs itself (a defect) is cut there too, and reads nothing."""
    clock = Clock()

    class Loop(asyncio.SelectorEventLoop):
        def time(self) -> float:
            return clock.t

    async def at(t: float) -> None:
        clock.t = t
        for _ in range(50):
            await asyncio.sleep(0)  # a yield, not a delay: the timers due by `t` run

    async def scenario() -> None:
        tail = Tail(error=OSError("questdb down"), now=True)

        async def read(symbol: str, spec: BarSpec, limit: int) -> BarTail:
            try:
                return await tail(symbol, spec, limit)
            except asyncio.CancelledError:  # cut: the reader's cleanup, a second cancel ends it
                await asyncio.sleep(unwind * store.timeout_s)
                raise

        store = SeriesStore(read, clock=clock)
        _held = await store.ensure(SYM, SPEC)  # the first read fails: due 5 s later
        tail.error = None
        tail.gate.clear()
        if hung == "refresh":
            monkeypatch.setattr(store, "refresh", lambda *_: asyncio.Event().wait())
        clock.t += RETRY_AFTER_S
        start, before, failed = clock.t, refreshed(), counted(FAILED, "timeout")
        bound = store.timeout_s + HEAL_REFRESH_MARGIN_S
        end = bound if result == "timeout" else store.timeout_s * (1 + unwind)
        with capture_logs() as logs:
            tick = asyncio.create_task(HealDriver(store).tick())
            await at(start)  # the refresh starts: its deadlines count from `start`
            await at(start + min(store.timeout_s, end - 0.5))  # the store's deadline, on time
            await at(start + end - 0.5)
            assert not tick.done()
            await at(start + end)
            assert tick.done() and tick.result() is None
        assert (since(before), counted(FAILED, "timeout") - failed) == ({result: 1}, hung == "read")
        assert [e["event"] for e in logs] == ["bars_heal_refresh_failed"] * (result == "timeout")
        assert store.due(clock.t) == ([] if hung == "read" else [(SYM, H)])

    with asyncio.Runner(loop_factory=Loop) as runner:
        runner.run(scenario())


def test_the_driver_bound_outlasts_the_production_reader_unwinding_a_cut_read() -> None:
    """`LazyPgWire` gives a cut query's connection up to `close_timeout_s` to close gracefully."""
    close_s = inspect.signature(LazyPgWire).parameters["close_timeout_s"].default
    assert close_s < HEAL_REFRESH_MARGIN_S <= close_s + 1.0


def missing(tail: Tail, miss: str) -> Tail:
    """Every read from now on misses: it fails, withholds a row (SR-E12-11) or skips one (#3614)."""
    if miss == "failed":
        tail.error = OSError("questdb down")
    else:
        skip = int(miss == "skipped")
        tail.error, tail.tail = None, BarTail(rows(*range(10)), skipped=skip, dropped=1 - skip)
    return tail


MISSES = pytest.mark.parametrize("miss", ["failed", "degraded"])


@pytest.mark.parametrize("miss", ["failed", "degraded", "skipped"])
async def test_reads_that_keep_missing_back_off_up_to_160_s(miss: str) -> None:
    """5, 10, 20, 40, 80, then 160 s, where it stays: each miss after the first doubles the
    interval, for the driver's `refresh` as for `ensure`. A read that keeps skipping a malformed
    row (#3614: never `hydrated`) backs off the same way, never re-read at the floor."""
    clock, tail = Clock(), missing(Tail(now=True), miss)
    store = SeriesStore(tail, clock=clock)
    _held = await store.ensure(SYM, SPEC)
    for k, wait in enumerate((1, 2, 4, 8, 16, 32, 32)):
        clock.t += wait * RETRY_AFTER_S - 0.5
        assert store.due(clock.t) == [] and not await store.refresh(SYM, H)
        clock.t += 0.5
        assert store.due(clock.t) == [(SYM, H)] and not await store.refresh(SYM, H)
        assert tail.calls == k + 2
    assert MAX_GAP_BACKOFF * RETRY_AFTER_S == 160


@MISSES
async def test_a_miss_streak_logs_its_first_read_only_and_a_clean_read_ends_it(miss: str) -> None:
    """Three misses log once (the failure counter counts each); a clean read ends the streak, so
    the first miss after a live swap logs again and is read again 5 s later."""
    clock, tail = Clock(), missing(Tail(rows(*range(10)), now=True), miss)
    store = SeriesStore(tail, clock=clock)
    event, failed = f"bars_series_hydrate_{miss}", counted(FAILED, "connection")
    with capture_logs() as logs:
        _held = await store.ensure(SYM, SPEC)
        for wait in (1, 2):
            clock.t += wait * RETRY_AFTER_S
            await store.refresh(SYM, H)
        tail.error, tail.tail = None, BarTail(rows(*range(10)))
        clock.t += 4 * RETRY_AFTER_S
        await store.refresh(SYM, H)  # clean: `hydrated`, the streak ends
        await emit(store, up("close", 0, shift=20), generation=1)  # a live swap: not hydrated
        missing(tail, miss)
        clock.t += RETRY_AFTER_S
        await store.refresh(SYM, H)
    assert ([e["event"] for e in logs if e["event"] == event], tail.calls) == ([event] * 2, 5)
    assert counted(FAILED, "connection") - failed == (4 if miss == "failed" else 0)
    assert store.due(clock.t + RETRY_AFTER_S) == [(SYM, H)]


@pytest.mark.parametrize(
    ("miss", "live", "wait"),
    [
        ("failed", "swap", 4),
        ("failed", "gap", 4),
        ("degraded", "swap", 4),
        ("degraded", "gap", 1),
        ("skipped", "swap", 4),
        ("skipped", "gap", 1),
    ],
    ids=[
        "failed-swap",
        "failed-gap",
        "degraded-swap",
        "degraded-gap",
        "skipped-swap",
        "skipped-gap",
    ],
)
async def test_a_gap_seen_live_ends_a_streak_of_degraded_and_skipping_reads_only(
    miss: str, live: str, wait: int
) -> None:
    """Three misses ask for 20 s. A live swap keeps it, and so does a gap seen live after failed
    reads (storage has not answered); after degraded or skipping reads (#3614), which complete, it
    ends the streak, so the new hole is read 5 s later (H2's interval)."""
    clock, tail = Clock(), missing(Tail(now=True), miss)
    store = SeriesStore(tail, clock=clock)
    _held = await store.ensure(SYM, SPEC)
    await emit(store, up("close", 0), up("close", 1))
    for k in (1, 2):
        clock.t += k * RETRY_AFTER_S
        await store.refresh(SYM, H)
    if live == "gap":
        await emit(store, up("close", 12))
    else:
        await emit(store, up("close", 0, shift=20), generation=1)
    assert store.gapped(SYM, H) == (live == "gap") and tail.calls == 3
    clock.t += wait * RETRY_AFTER_S - 0.5
    assert store.due(clock.t) == []
    clock.t += 0.5
    assert store.due(clock.t) == [(SYM, H)]


def test_the_refresh_counter_is_live_exported_and_bounded_by_its_five_results() -> None:
    spec = next(s for s in CATALOGUE if s.name == REFRESHES)
    assert (spec.kind, spec.labels, spec.max_series) == ("counter", ("result",), len(RESULTS))
    assert (spec.status, spec.exported, REFRESHES in EXPORTED_NAMES) == ("live", True, True)
    helps = {m.name: m.documentation for m in REGISTRY.collect()}
    assert helps[REFRESHES.removesuffix("_total")] == spec.help
