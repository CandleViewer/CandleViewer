"""#2787 D2-G2: what each `LazyPgWire` counts under its `wire` name (C-2.18 signals): a discard by
reason (`error`; `query_timeout`, the wire's own; `cancelled`, the caller's, during its query), a
call abandoned (cancelled before its query started, waiting for the lock or a connect), and the
wait for the lock, on the wire's clock, observed when granted. Then what a discard's close does:
a cancellation during it propagates, a hung or a failing one is abandoned by `terminate()`. Fake
connections; the loop is only yielded to (`until`), and a test that needs a timer, or must end
every task it starts, runs on a loop whose timers keep the test's clock. No network, no QuestDB."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.observability import pgwire_metrics as pm
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.storage.questdb.wiring import LazyPgWire

EPS = 0.001
WIRE: pm.WireName = "bars_hydrate"  # not `bars`: a series under another name shows as a miss


class Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


async def until(cond: Callable[[], bool], what: str) -> None:
    """Yield to the loop until `cond()` holds: a yield, not a delay; it fails, never hangs."""
    for _ in range(1_000):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never reached: {what}")


async def settled() -> None:
    await until(lambda: asyncio.all_tasks() == {asyncio.current_task()}, "nothing is left pending")


def run_on(clock: Clock, scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run `scenario` on its own loop, whose timers keep `clock`; it only yields, so the loop never
    waits on real time, and it must end every task it starts. Once it ends, passed or failed, the
    clock runs 10**6 times real time: a task a failed scenario left on a timer then ends in the
    runner's cleanup, so the failure is reported instead of hanging the run."""
    ended: list[float] = []

    class Loop(asyncio.SelectorEventLoop):
        def time(self) -> float:
            return clock.t + (time.monotonic() - ended[0]) * 1e6 if ended else clock.t

    async def run() -> None:
        try:
            await scenario()
        finally:
            ended.append(time.monotonic())

    with asyncio.Runner(loop_factory=Loop) as runner:
        runner.run(run())


def sample(name: str, **labels: str) -> float:
    return float(REGISTRY.get_sample_value(name, labels) or 0.0)


def counts(wire: str = WIRE) -> dict[str, float]:
    """Each discard reason, the abandoned calls and the waits observed, on `wire`."""
    got: dict[str, float] = {
        r: sample("questdb_pgwire_discards_total", wire=wire, reason=r) for r in pm.DISCARD_REASONS
    }
    got["abandoned"] = sample("questdb_pgwire_abandoned_total", wire=wire)
    got["waits"] = sample("questdb_pgwire_lock_wait_seconds_count", wire=wire)
    return got


def moved(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {k: after[k] - before[k] for k in before if after[k] != before[k]}


class Db:
    """`connect` and its connection in one: a connect waits for `connecting`; a query raises
    `error`, or waits for `hold`, then answers `rows`; with `hang_close`, a close waits for
    `terminate()` to abort it, as asyncpg's does on a dead server."""

    def __init__(
        self, error: BaseException | None = None, rows: Any = None, hang_close: bool = False
    ) -> None:
        self.error, self.hang_close = error, hang_close
        self.rows = [{"n": 1}] if rows is None else rows
        self.hold, self.connecting, self.aborted = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.hold.set()
        self.connecting.set()
        self.connects = self.queries = self.closes = 0

    async def connect(self, **_: object) -> Db:
        self.connects += 1
        await self.connecting.wait()
        return self

    async def fetch(self, sql: str, *params: object) -> Any:
        self.queries += 1
        if self.error is not None:
            raise self.error
        await self.hold.wait()
        return self.rows

    async def close(self) -> None:
        self.closes += 1
        if self.hang_close:
            await self.aborted.wait()

    def terminate(self) -> None:
        self.aborted.set()


class FailingClose(Db):
    async def close(self) -> None:
        await super().close()
        raise OSError("close failed")


def wire(db: Db, clock: Clock | None = None, query_timeout_s: float = 10.0) -> LazyPgWire:
    return LazyPgWire(
        "h", 1, "u", "p", name=WIRE, connect=db.connect, clock=clock or Clock(),
        query_timeout_s=query_timeout_s,
    )  # fmt: skip


@pytest.mark.parametrize("error", [OSError("down"), TimeoutError()])
async def test_a_query_that_raises_is_an_error_discard_on_its_wire(error: Exception) -> None:
    """A `TimeoutError` of the driver's own is an error: only the wire's deadline is a timeout."""
    db, before, other = Db(error), counts(), counts("bars")
    with pytest.raises(type(error)):
        await wire(db).fetch("q")
    assert moved(before, counts()) == {"error": 1, "waits": 1} and db.closes == 1
    assert moved(other, counts("bars")) == {}


def test_a_query_past_the_wires_own_timeout_is_a_query_timeout_discard() -> None:
    clock, before = Clock(), counts()

    async def scenario() -> None:
        db = Db()
        db.hold.clear()
        call = asyncio.create_task(wire(db, clock).fetch("q"))
        await until(lambda: db.queries == 1, "the query runs")
        clock.t += 10.0 + EPS
        await until(call.done, "the wire's own timeout ends it")
        assert isinstance(call.exception(), TimeoutError) and db.closes == 1

    run_on(clock, scenario)
    assert moved(before, counts()) == {"query_timeout": 1, "waits": 1}


@pytest.mark.parametrize("during", ["query", "connect"])
async def test_a_call_cancelled_in_its_query_is_a_discard_and_before_it_is_abandoned(
    during: str,
) -> None:
    db, before = Db(), counts()
    (db.hold if during == "query" else db.connecting).clear()
    w = wire(db)
    call = asyncio.create_task(w.fetch("q"))
    await until(lambda: db.connects == 1, "the call holds the lock and connects")
    call.cancel()
    await until(call.done, "the call ends")
    assert call.cancelled() and w._conn is None
    counted = {"cancelled": 1} if during == "query" else {"abandoned": 1}
    assert moved(before, counts()) == {**counted, "waits": 1}  # the lock was granted either way
    assert (db.queries, db.closes) == ((1, 1) if during == "query" else (0, 0))


async def test_a_call_cancelled_while_it_waits_for_the_lock_is_abandoned_not_waited() -> None:
    db, before = Db(), counts()
    db.hold.clear()
    w = wire(db)
    first = asyncio.create_task(w.fetch("q"))
    waiting = asyncio.create_task(w.fetch("q"))  # runs right after `first`, so it queues
    await until(lambda: db.queries == 1, "the first query runs; the second call waits")
    waiting.cancel()
    await until(waiting.done, "the waiting call ends")
    db.hold.set()
    assert await first == [{"n": 1}] and waiting.cancelled() and db.queries == 1
    assert moved(before, counts()) == {"abandoned": 1, "waits": 1}  # `first`'s grant only


@pytest.mark.parametrize("via", ["close", "query", "cancel"])
def test_a_cancel_during_the_close_propagates_and_the_connection_is_terminated_and_dropped(
    via: str,
) -> None:
    async def scenario() -> None:
        before, db = counts(), Db(OSError("down") if via == "query" else None, hang_close=True)
        w = wire(db)
        if via == "close":
            await w.fetch("q")  # opens the connection
        call = asyncio.create_task(w.close() if via == "close" else w.fetch("q"))
        if via == "cancel":  # a held query is cancelled: its discard closes, and is cancelled too
            db.hold.clear()
            await until(lambda: db.queries == 1, "the query is held")
            call.cancel()
        await until(lambda: db.closes == 1, "the close hangs")
        call.cancel()
        await until(call.done, "the call ends")
        assert call.cancelled() and db.aborted.is_set() and w._conn is None
        counted = {"close": {}, "query": {"error": 1}, "cancel": {"cancelled": 1}}[via]
        assert moved(before, counts()) == {**counted, "waits": 1}  # once, under its own reason
        await settled()

    run_on(Clock(), scenario)


def test_a_hung_close_ends_by_terminate_at_its_bound_and_raises_nothing() -> None:
    clock = Clock()

    async def scenario() -> None:
        db = Db(hang_close=True)
        w = wire(db, clock)
        await w.fetch("q")
        call = asyncio.create_task(w.close())
        await until(lambda: db.closes == 1, "the close hangs")
        clock.t += 5.0 + EPS  # the wire's close bound
        await until(call.done, "the bound ends the close")
        assert call.result() is None and db.aborted.is_set() and w._conn is None
        await settled()

    run_on(clock, scenario)


async def test_a_raising_close_still_terminates_the_connection_and_raises_nothing() -> None:
    db = FailingClose()
    w = wire(db)
    await w.fetch("q")
    await w.close()
    assert (db.closes, db.aborted.is_set(), w._conn) == (1, True, None)


async def test_the_lock_wait_is_observed_on_the_wires_clock_when_it_is_granted() -> None:
    db, clock, name = Db(), Clock(), "questdb_pgwire_lock_wait_seconds"
    db.hold.clear()
    w = wire(db, clock)
    le = {b: sample(f"{name}_bucket", wire=WIRE, le=str(b)) for b in (0.001, 1.0, 2.0)}
    total = sample(f"{name}_sum", wire=WIRE)
    calls = [asyncio.create_task(w.fetch("q")) for _ in range(2)]  # both ask at t; one waits
    await until(lambda: db.queries == 1, "the first query runs; the second call waits")
    clock.t += 1.5
    db.hold.set()  # the first call ends: the second is granted 1.5 s after it asked
    await asyncio.gather(*calls)
    assert sample(f"{name}_sum", wire=WIRE) - total == 1.5
    after = {b: sample(f"{name}_bucket", wire=WIRE, le=str(b)) - n for b, n in le.items()}
    assert after == {0.001: 1, 1.0: 1, 2.0: 2}


async def test_a_sibling_has_the_endpoint_and_bounds_but_its_own_lock_and_connection() -> None:
    db, clock = Db(), Clock()
    base = LazyPgWire(
        "h", 8812, "u", "p", name="bars", connect=db.connect, clock=clock, connect_timeout_s=1.0,
        query_timeout_s=2.0, close_timeout_s=3.0, backoff_base_s=4.0, backoff_max_s=5.0,
        degraded_after=6,
    )  # fmt: skip
    twin = base.sibling("bars_hydrate")
    attrs = ("_args", "_connect", "_clock", "_connect_timeout_s", "_query_timeout_s",
             "_close_timeout_s", "_base_s", "_max_s", "_degraded_after")  # fmt: skip
    assert [getattr(twin, a) for a in attrs] == [getattr(base, a) for a in attrs]
    assert twin.name == "bars_hydrate" and twin._lock is not base._lock
    await base.fetch("q")
    await twin.fetch("q")
    assert db.connects == 2  # one connection each


def test_each_series_is_its_catalogue_row_bounded_by_the_closed_names() -> None:
    rows, wires = {s.name: s for s in CATALOGUE}, len(pm.WIRE_NAMES)
    for metric, labels, cap in (
        (pm.questdb_pgwire_discards_total, ("wire", "reason"), wires * len(pm.DISCARD_REASONS)),
        (pm.questdb_pgwire_abandoned_total, ("wire",), wires),
        (pm.questdb_pgwire_lock_wait_seconds, ("wire",), wires),
    ):
        (family,) = metric.collect()
        row = rows[family.name + ("_total" if family.type == "counter" else "")]
        assert (row.labels, row.help, row.max_series) == (labels, family.documentation, cap)
        assert (row.status, row.exported) == ("live", True)
    assert rows["questdb_pgwire_lock_wait_seconds"].buckets == pm.LOCK_WAIT_BUCKETS
    assert (wires, len(pm.DISCARD_REASONS)) == (6, 3)
