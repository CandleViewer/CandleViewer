"""#913 slice 3E (E29-T04): the OMS runtime (`oms_wiring.OmsRuntime`, 20 Sec.6.2) on fakes. Its
composition for the process's environment, the sink it takes, builds or refuses (rulings Q4 to Q6),
the interim announcements, closing what a failed composition built, and one facade per process;
its lifecycle: the startup's waits, `run`, the stop's drain, and the state `/readyz` gives; and
the startup sweep after a crash. No I/O: in-memory stores, a fake venue, and a clock that moves only
when the runtime sleeps on it."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer import oms_wiring
from candleviewer.api.health import make_health_router
from candleviewer.app import _oms_state
from candleviewer.audit.machine_events import MachineEventUnavailable
from candleviewer.audit.wal import AuditWal, lock_wal_file
from candleviewer.audit.writer import AuditUnavailable, keyed_record_id
from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, Position, RateLane
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.cancel_all import CancelAllRequest
from candleviewer.oms.cancel_all_coalescer import CancelAllCoalescer
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.day_figures import DayRiskFigures
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsNotReady,
    OrderEntryRefused,
    StoreUnavailable,
)
from candleviewer.oms.exits import ExitCaller, ExitOutcome, OrderExits
from candleviewer.oms.fakes import FakeClockHealth, InMemoryOrderStore, InMemorySubmissionStore
from candleviewer.oms.order_machine import OrderMachines
from candleviewer.oms.ports import NoDayFigures, PositionKey, SubmitActor
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.oms_lane import HOP_TIMEOUT_S, LANE_JOIN_S, LaneStopped
from candleviewer.oms_wiring import (
    ENVIRONMENT_FENCE_GRACE_S,
    ENVIRONMENT_LOCK_TIMEOUT_S,
    HYDRATE_CONCURRENCY,
    LANE_STALE_S,
    LANE_TICK_S,
    STARTUP_POLL_S,
    SWEEP_MAX_FAILURES,
    SWEEP_RETRY_S,
    SWEEP_STATEMENT_TIMEOUT_MS,
    CommandAccounts,
    GroupStores,
    LaneHeartbeat,
    OmsRuntime,
    OmsStores,
    TradingAccountsBinding,
    build_oms_runtime,
    pg_stores,
)
from candleviewer.settings import OMS_STOP_RESERVE_S, Settings
from candleviewer.settings import Environment as Env
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import ChainTripLatch, DegradedLatchError, MachineKey
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.statechart_wiring import PersistOps
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import NewOrder, ScopedOrder
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow
from candleviewer.storage.repositories.session_lock_sqlalchemy import SqlAlchemySessionLock
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests._signing import fake_capability
from tests.unit.oms import command_rig as cr
from tests.unit.oms import order_rig
from tests.unit.oms.order_rig import ACCOUNT, GATES, Pager, order_of
from tests.unit.oms.submit_rig import REGISTRY, Profiles, ReadOnly

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
INTERIMS = ("stop_resolver", "risk_gate", "arm_records", "atr", "kill_switch")


class Port(FakeTradingPort):
    """The venue's port of one environment, which the runtime owns and closes."""

    closed = False

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class Venue:
    """The adapter's service: a port per call, and the adapter's lane waits."""

    ports: list[Port] = field(default_factory=list)

    def trading_port(self, env: str, *, clock_offset_ms: Any = None) -> Port:
        self.ports.append(Port(environment=cast(Environment, env)))
        return self.ports[-1]

    def lane_waits(self) -> Mapping[RateLane, float]:
        return {"critical": 5.0, "entry": 0.75, "poll": 5.0}

    def key_refusal(self, error: Exception) -> tuple[str, int] | None:
        return None


@dataclass
class Clock:
    """The runtime's monotonic clock, which its sleep moves: nothing waits on the wall clock."""

    s: float = 100.0
    slept: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.s

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.s += seconds
        await asyncio.sleep(0)


class Flag:
    """A flag view, on and unread until `read()`."""

    def __init__(self) -> None:
        self._read = asyncio.Event()

    def __call__(self) -> bool:
        return True

    async def first_read(self) -> None:
        await self._read.wait()

    def read(self) -> None:
        self._read.set()


class Sink(InMemoryMachineEventSink):
    """The lane's own sink the stores build (#913 L2), at `wal`; its start and stop land in the
    world's log."""

    def __init__(self, log: list[str], fail: Exception | None = None, wal: str = "") -> None:
        super().__init__()
        self.log, self.fail, self.wal = log, fail, wal

    async def start(self) -> None:
        self.log.append("sink.start")
        if self.fail is not None:
            raise self.fail

    async def stop(self) -> None:
        self.log.append("sink.stop")


@dataclass
class Writer:
    """The order lane's own audit writer the stores build (#913 L2): each append, by its action
    and reason; a keyed one stored as the writer stores it, under `keyed_record_id(action, name)`,
    so one whose id is already stored lands nothing (`ON CONFLICT (record_id) DO NOTHING`, #4587);
    its start and stop land in `log`, the world's, and each stop's grace in `graces`."""

    actions: list[tuple[str, str | None]] = field(default_factory=list)
    stored: set[UUID] = field(default_factory=set)
    log: list[str] = field(default_factory=list)
    graces: list[float] = field(default_factory=list)

    async def start(self) -> None:
        self.log.append("audit.start")

    async def stop(self, grace_s: float = 5.0) -> None:
        self.log.append("audit.stop")
        self.graces.append(grace_s)

    async def emit(self, action: str, **fields: Any) -> None:
        self.actions.append((action, fields.get("reason")))

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        key = keyed_record_id(action, name)
        if key not in self.stored:
            self.stored.add(key)
            self.actions.append((action, fields.get("reason")))


@dataclass
class Lock:
    """The environment's lock (SEC-S3N-01): held unless another process holds it (`elsewhere`),
    or refused with the next of `fails`; each take and give-up lands in `log`, the world's, and
    each ask notes whether B1's process-wide ports were wired then (a facade existed). Its
    watchdog's probe (`confirm`, CR-S3L2-03) answers `confirmed`, or raises `unconfirmed`."""

    log: list[str] = field(default_factory=list)
    elsewhere: bool = False
    fails: list[Exception] = field(default_factory=list)
    wired: list[bool] = field(default_factory=list)
    confirmed: bool = True
    unconfirmed: Exception | None = None
    confirms: int = 0

    async def acquire(self) -> bool:
        self.wired.append(b01.ports_wired())
        if self.fails:
            raise self.fails.pop(0)
        if not self.elsewhere:
            self.log.append("lock.acquire")
        return not self.elsewhere

    async def confirm(self) -> bool:
        self.confirms += 1
        if self.unconfirmed is not None:
            raise self.unconfirmed
        return self.confirmed

    async def release(self) -> None:
        self.log.append("lock.release")


class Beats:
    """The lane heartbeat's clock and wait (ruling 2): the clock moves only when a test moves it
    (`s`), and each wait between ticks ends only when a test lets one more tick happen (`tick`), on
    the loop the heartbeat runs on."""

    def __init__(self) -> None:
        self.s = 0.0
        self._next: asyncio.Event | None = None

    def clock(self) -> float:
        return self.s

    async def wait(self, seconds: float) -> None:
        self._next = asyncio.Event()
        await self._next.wait()

    def tick(self) -> None:
        if self._next is not None:
            self._next.set()


class Heart(LaneHeartbeat):
    """The lane's heartbeat on the world's beats; its end lands in the world's log."""

    def __init__(self, lock: Any, pager: Any, beats: Beats, log: list[str]) -> None:
        super().__init__(lock, pager, clock=beats.clock, wait=beats.wait)
        self.log = log

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            self.log.append("heartbeat.end")


class InlineLane:
    """The order lane on the test's own loop, so these tests step one loop (`test_order_lane`
    runs the runtime on `OrderLane`'s thread): `call` tracks each task as the lane does, and its
    stop is recorded (CR-S3L1B-03)."""

    dead = stopped = False

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        return None

    def call[T](
        self, coro: Coroutine[Any, Any, T], *, timeout_s: float | None = None
    ) -> asyncio.Future[T]:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def idle(self) -> None:
        while pending := [task for task in self.tasks if task is not asyncio.current_task()]:
            await asyncio.wait(pending)

    async def stop(self) -> None:
        self.stopped = True


class Refusing(InlineLane):
    """A lane that refuses every call with `error`, closing its coroutine unrun, and notes each
    call's bound."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error, self.bounds = error, list[float | None]()

    def call[T](
        self, coro: Coroutine[Any, Any, T], *, timeout_s: float | None = None
    ) -> asyncio.Future[T]:
        coro.close()
        self.bounds.append(timeout_s)
        raise self.error


class Recording(InlineLane):
    """The inline lane, noting what each call carries, by its coroutine's name, and its bound."""

    def __init__(self) -> None:
        super().__init__()
        self.hops = list[tuple[str, float | None]]()

    def call[T](
        self, coro: Coroutine[Any, Any, T], *, timeout_s: float | None = None
    ) -> asyncio.Future[T]:
        self.hops.append((getattr(coro, "__qualname__", "?"), timeout_s))
        return super().call(coro, timeout_s=timeout_s)


@dataclass
class World:
    """Everything a runtime is built over, the in-memory order store its stores' tables."""

    store: InMemoryOrderStore = field(default_factory=lambda: InMemoryOrderStore(lambda: T0))
    venue: Venue = field(default_factory=Venue)
    clock: Clock = field(default_factory=Clock)
    flags: tuple[Flag, Flag] = field(default_factory=lambda: (Flag(), Flag()))
    standings: Any = field(default_factory=lambda: SimpleNamespace(read_once=True))
    metrics: Metrics = field(default_factory=lambda: Metrics("demo"))
    pager: Pager = field(default_factory=Pager)
    writer: Writer = field(default_factory=Writer)
    log: list[str] = field(default_factory=list)
    accounts: list[Any] = field(default_factory=list)
    sink_fails: Exception | None = None
    audit_fails: Exception | None = None
    #: The bytes the stores' probe finds in `CV_MACHINE_EVENT_WAL_PATH` that Postgres has not
    #: taken, and how often it was asked (SEC-S3L2-03).
    unclaimed: int = 0
    probes: int = 0
    lanes: list[InlineLane] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)
    #: The alarm each build of the lane's writer was given (ruling 4).
    alarms: list[Callable[[str], Awaitable[None]]] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    beats: Beats = field(default_factory=Beats)
    #: Each wait of the fencing grace (SEC-S3L2-01), on the world's clock, apart from `sleep`'s.
    graces: list[float] = field(default_factory=list)
    #: The serving loop's watch of the lane (SEC-S3L2-04): each wait's length, and its end, one
    #: more watch a test lets happen (`watches.tick`).
    watched: list[float] = field(default_factory=list)
    watches: Beats = field(default_factory=Beats)

    def __post_init__(self) -> None:
        self.writer.log = self.lock.log = self.log
        self.health = FakeClockHealth(self.clock)
        self.health.measure()
        self.ingestion = SimpleNamespace(
            clock=self.health, tickers=None, instruments=None, clock_offset_ms=lambda: None
        )

    def stores(self) -> OmsStores:
        store = self.store

        async def release() -> None:
            self.log.append("pool.release")

        def audit(alarm: Callable[[str], Awaitable[None]] | None = None) -> Writer:
            if alarm is not None:
                self.alarms.append(alarm)
            if self.audit_fails is not None:
                raise self.audit_fails
            return self.writer

        def sink(wal: str) -> Sink:
            self.sinks.append(Sink(self.log, self.sink_fails, wal))
            return self.sinks[-1]

        def unclaimed() -> int:
            self.probes += 1
            return self.unclaimed

        return OmsStores(
            orders=store, executions=store.executions, submissions=store.submissions,
            anchors=store.anchors, stops=store.stops, groups=cast(GroupStores, None),
            unclaimed=unclaimed,
            accounts=InMemoryTradingAccountReads(*self.accounts), sweep=store, audit=audit,
            sink=sink, lock=self.lock, release=release,
        )  # fmt: skip

    def runtime(
        self, environment: str = "demo", *, live_on: bool = False, bundle: Any = None, **over: Any
    ) -> OmsRuntime:
        settings = Settings(environment=Env(environment), trading_live_enabled=live_on)
        feed = SimpleNamespace(bind=lambda _b: SimpleNamespace(publish=lambda *_a, **_k: None))
        built: dict[str, Any] = {
            "venue": self.venue, "ingestion": self.ingestion, "read_only": ReadOnly(),
            "metrics": self.metrics, "gate": SimpleNamespace(refusal=lambda _account: None),
            "standings": self.standings,
            "live_enabled": self.flags[1], "profiles": Profiles(), "persistence": bundle,
            "feed": feed, "stores": self.stores, "pager": self.pager, "now": lambda: T0,
            "monotonic": self.clock, "registry": REGISTRY, "oms_enabled": self.flags[0],
            "sleep": self.clock.sleep, "lane": self.lane, "heartbeat": self.heartbeat,
            "fencing": self.fencing, "watch": self.watch,
        }  # fmt: skip
        return OmsRuntime(settings, **(built | over))

    async def watch(self, seconds: float) -> None:
        self.watched.append(seconds)
        await self.watches.wait(seconds)

    async def fencing(self, seconds: float) -> None:
        self.graces.append(seconds)
        self.clock.s += seconds
        await asyncio.sleep(0)

    def heartbeat(self, lock: Any, pager: Any) -> Heart:
        return Heart(lock, pager, self.beats, self.log)

    def lane(self) -> InlineLane:
        self.lanes.append(InlineLane())
        return self.lanes[-1]

    def gauge(self, port: str) -> float:
        line = f'oms_interim_ports{{env="demo",port="{port}"}}'
        text = generate_latest(self.metrics.registry).decode()
        return next(
            float(row.rsplit(" ", 1)[1]) for row in text.splitlines() if row.startswith(line)
        )


@asynccontextmanager
async def started(runtime: OmsRuntime) -> AsyncIterator[OmsRuntime]:
    """The runtime started, with B1's command attempts its own (one facade per process), then
    stopped."""
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        await runtime.start()
        yield runtime
    finally:
        await runtime.stop()
        b01._ATTEMPTS = saved


def failed_closed(logs: list[Any]) -> list[str]:
    return [e["error"] for e in logs if e["event"] == "oms_runtime_failed_closed"]


def failed_phases(logs: list[Any]) -> list[str]:
    return [e["phase"] for e in logs if e["event"] == "oms_runtime_failed_closed"]


async def settle() -> None:
    for _ in range(64):
        await asyncio.sleep(0)


async def until(done: Callable[[], bool]) -> None:
    """Turn the loop until `done()`, at most 10 000 times: a bound on the test, not a time."""
    for _ in range(10_000):
        if done():
            return
        await asyncio.sleep(0)
    raise AssertionError("never happened")


async def test_start_composes_the_process_environment_only_and_announces_each_interim() -> None:
    world = World()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            [port] = world.venue.ports
            assert port.environment == "demo" and b01.ports_wired()
            parts = runtime._composed()
            assert parts.submission._anchors is parts.anchors  # SEC-S3D-02: the one service
            exits = parts.exits._d  # slice 4: the exits drive the pipeline's facade and port
            assert (exits.machines, exits.commands) == (
                parts.submission._machines, parts.submission._commands,
            )  # fmt: skip
            # and read the profile cache, the serving loop's, through the pipeline's one bridge
            assert exits.profiles is parts.submission._deps.profiles
            assert isinstance(exits.profiles, oms_wiring.ServedProfiles)
            assert exits.environment == parts.route.environment == "demo"
            cancel_all = parts.cancel_all  # S4-E: over that exit service and the order store
            assert cancel_all._exits is parts.exits
            assert cast(object, cancel_all._reads) is parts.route.orders  # the one repository
            # S4-S-b2: the size step and an accepted amend drop the one figures port's cache
            figures = parts.submission._deps.figures
            assert isinstance(figures, DayRiskFigures)
            assert parts.submission._commands._figures is figures
            assert world.log == STARTED and world.lock.wired == [False]  # before the facade
    warned = [e["port"] for e in logs if e["event"] == "oms_interim_port"]
    assert warned == [*INTERIMS, "machine_event_sink", "risk_figures"]  # one WARNING each
    runtime_ports = (*INTERIMS, "machine_event_sink", "risk_figures")
    assert [world.gauge(name) for name in runtime_ports] == [1.0] * 7
    assert world.log == [*STARTED, *STOPPED] and port.closed  # the lock released last
    assert not b01.ports_wired()


async def test_the_router_and_cancel_all_share_the_one_fold_port_before_the_serving_hop() -> None:
    """CR-S4F-09 (S4-F): the OMS reaches the venue through the cancel-all fold port the wiring
    builds. The router routes the environment to it, so the submit pipeline and B1's command
    port meet it, and cancel-all's fold port is that same instance. It wraps the served port, so
    the folds run on the order lane, before the hop to the serving loop; its calls still out at
    the stop end once the machines have stopped."""
    world = World()
    async with started(world.runtime()) as runtime:
        parts = runtime._composed()
        folds = parts.submission._router.port_for("demo")
        assert isinstance(folds, CancelAllCoalescer)
        assert isinstance(folds._inner, oms_wiring.ServedPort)
        commands = cast(OmsCommandPort, parts.exits._d.commands)
        assert commands._router.port_for("demo") is folds
        assert parts.cancel_all._folds is not None and parts.cancel_all._folds[0] is folds
        names = [name for name, _ in parts.closers]
        assert names.index("cancel_all_folds") == names.index("machines") + 1


#: What a composed runtime has started, in order (#913 L2): the environment's lock, then the lane's
#: own writer and sink; and what its stop closes, in order, the lock last.
STARTED = ["lock.acquire", "audit.start", "sink.start"]
STOPPED = ["sink.stop", "audit.stop", "pool.release", "heartbeat.end", "lock.release"]
_SINK_WAL = Path(Settings().machine_event_wal_path)
_BESIDE = str(_SINK_WAL.with_name(f"oms_lane.{_SINK_WAL.name}"))


@pytest.mark.parametrize(
    ("environment", "live_on", "with_bundle", "wal"),
    [
        ("demo", True, False, _BESIDE),
        ("testnet", True, False, _BESIDE),
        ("live", False, False, _BESIDE),
        ("live", True, True, _BESIDE),
        ("live", True, False, None),
    ],
)
async def test_the_lane_has_its_own_sink_beside_a_bundles_and_none_on_live_with_the_setting_on(
    environment: str, live_on: bool, with_bundle: bool, wal: str | None
) -> None:
    """Rulings Q4 to Q6 and Q13 (20 Sec.6.2): the order lane builds and owns its `machine_events`
    sink, in demo and testnet whatever the setting says and in live while it is off, at
    `oms_lane.<name>` beside `CV_MACHINE_EVENT_WAL_PATH`, a bundle composed or not (SEC-S3L2-03),
    taking only a bundle's latch; a live process with the setting on and no bundle fails closed:
    no sink, no order served."""
    world = World()
    bundle = SimpleNamespace(sink=InMemoryMachineEventSink(), latch=ChainTripLatch())
    runtime = world.runtime(environment, live_on=live_on, bundle=bundle if with_bundle else None)
    with capture_logs() as logs:
        async with started(runtime):
            if wal is None:
                assert failed_closed(logs) == ["NoMachineEventSink"] and not b01.ports_wired()
                assert world.pager.calls == ["oms_runtime_failed_closed: sink"]  # CR-S3E1-02
                assert failed_phases(logs) == ["sink"]
                assert world.venue.ports == [] and world.log == [] and world.lanes[0].stopped
                with pytest.raises(OmsNotReady):
                    _ = runtime.submission
            else:
                assert world.log == STARTED and [sink.wal for sink in world.sinks] == [wal]
                assert failed_closed(logs) == [] and b01.ports_wired()
                # S4-S-b3: the day figures on demo and testnet, the refusing stand-in on live
                [figures] = [e for e in logs if e.get("port") == "risk_figures"]
                served = NoDayFigures if environment == "live" else DayRiskFigures
                assert figures["serves"] == served.serves
                assert world.gauge("risk_figures") == 1.0
    assert world.gauge("machine_event_sink") == (0.0 if with_bundle else 1.0)


@pytest.mark.parametrize("bundled", [False, True])
async def test_the_oms_records_through_the_lanes_own_writer_and_sink_never_the_serving_loops(
    bundled: bool,
) -> None:
    """#913 L2 (29 CV-C13; rulings Q12, Q13): the sweep's records and the abandon's go to the
    writer the stores build for the lane, the facade's audit itself, never a hop to the serving
    loop's; B1's rows to the lane's own sink, the bundle's taking none."""
    world = World()
    await crashed(world)
    bundle = SimpleNamespace(sink=InMemoryMachineEventSink(), latch=ChainTripLatch())
    for flag in world.flags:
        flag.read()
    async with started(world.runtime(bundle=bundle if bundled else None)) as runtime:
        await runtime.wait_ready()
        assert runtime._composed().audit._writer is world.writer
    swept = ("sl.modified", "unplaced_entry_swept")
    assert {swept, ("orders.cancel", "kill_no_cancel_unsubmitted")} <= set(world.writer.actions)
    [sink] = world.sinks
    assert sink.rows and bundle.sink.rows == []


@pytest.mark.parametrize(
    ("fails", "phase", "log"),
    [
        ("build", "audit", ["lock.acquire", "pool.release", "lock.release"]),
        ("start", "audit_start", ["lock.acquire", "audit.stop", "pool.release", "lock.release"]),
    ],
)
async def test_a_lane_writer_that_cannot_build_or_start_fails_the_runtime_closed(
    fails: str, phase: str, log: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6 (#913 L2): a writer whose WAL another writer holds is refused at its build, and one that
    cannot start is stopped again (its lock dropped): either way the runtime fails closed, paged,
    with the port and the pool closed, and no sink started."""
    world = World(audit_fails=OSError("the WAL is locked") if fails == "build" else None)

    async def refused(self: Writer) -> None:
        raise OSError("the WAL is corrupt")

    if fails == "start":
        monkeypatch.setattr(Writer, "start", refused)
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            assert (failed_closed(logs), failed_phases(logs)) == (["OSError"], [phase])
            assert world.log == log and world.venue.ports[0].closed and not b01.ports_wired()
            assert world.pager.calls == [f"oms_runtime_failed_closed: {phase}"]
            with pytest.raises(OmsNotReady):
                _ = runtime.submission


def test_the_lanes_wal_files_are_its_own_beside_the_serving_loops() -> None:
    """D6: `oms_lane.<name>` in the serving loop's directory, never its file, however it is
    named; the sink's at that one path, a bundle composed or not (SEC-S3L2-03)."""
    settings = Settings(audit_wal_path="/v/audit/audit.wal", machine_event_wal_path="/v/me.wal")
    assert oms_wiring.lane_audit_wal(settings) == "/v/audit/oms_lane.audit.wal"
    assert oms_wiring.lane_sink_wal(settings) == "/v/oms_lane.me.wal"
    named = Settings(audit_wal_path="/v/oms_lane.audit.wal")
    assert oms_wiring.lane_audit_wal(named) != named.audit_wal_path


async def test_frames_no_sink_holds_fail_the_start_closed_critical_and_paged() -> None:
    """SEC-S3L2-03 (the Fable lens at 864fa082; 20 Sec.6.2; CR-S3L2X-06, one behaviour): without a
    bundle no sink of the process holds `CV_MACHINE_EVENT_WAL_PATH`, so frames there that Postgres
    has not taken, which a run before #913 L2 or a bundle's run left, refuse the start: logged
    CRITICAL with their size, failed closed by its phase and paged, `degraded`, never adopted or
    skipped."""
    world = World(unclaimed=1024)
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            assert (failed_closed(logs), failed_phases(logs)) == (
                ["UnclaimedMachineEvents"], ["sink_wal"]
            )  # fmt: skip
            left = [e for e in logs if e["event"] == "oms_machine_event_wal_unclaimed"]
            assert [(e["log_level"], e["pending_bytes"]) for e in left] == [("critical", 1024)]
            assert world.pager.calls == ["oms_runtime_failed_closed: sink_wal"]
            assert runtime.state == "degraded"


async def test_frames_no_sink_holds_refuse_the_start_before_the_lanes_sink_or_the_facade() -> None:
    """SEC-S3L2-03 (CR-S3L2X-06, one behaviour): the probe runs once, before the lane's sink or the
    facade exists, so the refused start built neither, and it closes its port and its pool."""
    world = World(unclaimed=1024)
    async with started(world.runtime()):
        assert world.probes == 1 and world.sinks == [] and not b01.ports_wired()
        assert world.log == ["pool.release"] and world.venue.ports[0].closed


async def test_with_a_bundle_the_file_its_sink_holds_is_never_probed() -> None:
    """SEC-S3L2-03 (CR-S3L2X-06, one behaviour): with a bundle, whose sink holds and drains
    `CV_MACHINE_EVENT_WAL_PATH`, the file is not asked, and the start goes on."""
    world = World(unclaimed=1024)
    bundle = SimpleNamespace(sink=InMemoryMachineEventSink(), latch=ChainTripLatch())
    async with started(world.runtime(bundle=bundle)) as runtime:
        assert world.probes == 0 and world.log == STARTED and runtime.state != "degraded"


async def test_pg_stores_probe_the_frames_postgres_has_not_taken_under_the_files_lock(
    tmp_path: Path,
) -> None:
    """SEC-S3L2-03: the stores' probe reads `CV_MACHINE_EVENT_WAL_PATH` under its lock, never the
    lane's own file: none when there is no file or its cursor is at its end, the bytes past the
    cursor otherwise, and another holder of its lock is the sink's refusal, not a guess."""
    wal = tmp_path / "machine_events.wal"
    stores = pg_stores(Settings(machine_event_wal_path=str(wal)), Metrics("demo"))
    assert await asyncio.to_thread(stores.unclaimed) == 0 and not wal.exists()
    left = AuditWal(wal)
    end = left.append({"machine_kind": "order", "entity_id": "a"})
    assert await asyncio.to_thread(stores.unclaimed) == end
    left.mark_committed(end)
    assert await asyncio.to_thread(stores.unclaimed) == 0
    left.append({"machine_kind": "order", "entity_id": "b"})
    held = lock_wal_file(wal)
    try:
        with pytest.raises(MachineEventUnavailable):
            await asyncio.to_thread(stores.unclaimed)
    finally:
        held.close()
    assert not (tmp_path / "oms_lane.machine_events.wal").exists()
    await stores.release()


async def test_the_stop_gives_the_lanes_writer_its_own_grace() -> None:
    """CR-S3L2-05: the stop gives the lane's writer `LANE_AUDIT_STOP_S` to empty its WAL into
    Postgres, inside its share of the reserve, never the writer's own default."""
    world = World()
    async with started(world.runtime()):
        pass
    assert world.writer.graces == [oms_wiring.LANE_AUDIT_STOP_S]


async def test_the_lane_writers_alarm_pages_the_first_of_each_window_per_cause() -> None:
    """Ruling 4 (the orchestrator's of 2026-10-25 12:22Z; CR-S3L2-08): the lane writer's fail-closed
    alarm, a refused append or its flusher's death, pages through the runtime's pager, so an
    `audit_unavailable` refusal is never a silent outage; the first of each `LANE_AUDIT_PAGE_S`
    window per cause on the runtime's clock, never once a refused record."""
    world, window = World(), oms_wiring.LANE_AUDIT_PAGE_S
    full, died = "audit WAL unavailable: AuditWalFull", "audit flusher died: OSError"
    async with started(world.runtime()):
        [alarm] = world.alarms
        for _ in range(3):  # a burst of refused records: one page
            await alarm(full)
        world.clock.s += window - 0.001
        await alarm(full)  # still its window
        await alarm(died)  # another cause pages at once
        world.clock.s += 0.001
        await alarm(full)  # its next window
    paged = [f"oms_lane_audit_alarm: {cause}" for cause in (full, died, full)]
    assert (world.pager.calls, world.pager.severities) == (paged, ["page"] * 3)


async def test_a_clock_stepped_back_behind_the_lane_writers_last_page_ends_its_window() -> None:
    """Ruling 4 (CR-S3L2X-04): the runtime's clock stepped back behind the last page reads as the
    window's end, so the next alarm of the cause pages, never a window held open for as long as
    the clock was stepped back."""
    world = World()
    full = "audit WAL unavailable: AuditWalFull"
    async with started(world.runtime()):
        [alarm] = world.alarms
        await alarm(full)
        world.clock.s -= 1.0  # stepped back: inside the window, read forward
        await alarm(full)
    assert world.pager.calls == [f"oms_lane_audit_alarm: {full}"] * 2


async def test_pg_stores_build_the_lanes_writer_with_the_alarm_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 4: the writer `pg_stores` builds for the lane, on its own WAL, fires the alarm the
    runtime gives it when an append is refused, its WAL unwritable: the record is refused and the
    alarm names the error's class alone."""
    stores = pg_stores(Settings(audit_wal_path=str(tmp_path / "audit.wal")), Metrics("demo"))
    alarms = list[str]()

    async def alarm(cause: str) -> None:
        alarms.append(cause)

    def unwritable(_record: Any) -> int:
        raise OSError("the disk is gone")

    writer: Any = stores.audit(alarm)
    await writer.start()
    monkeypatch.setattr(writer._wal, "append", unwritable)
    try:
        with pytest.raises(AuditUnavailable):
            await writer.emit("auth.logout", actor_label="system:test")
    finally:
        await writer.stop(1)
        await stores.release()
    assert alarms == ["audit WAL unavailable: OSError"]
    assert (tmp_path / "oms_lane.audit.wal").exists()


@pytest.mark.parametrize("ends", ["failed", "cancelled"])
async def test_the_composes_own_unwind_keeps_within_the_reserve_less_the_join(
    ends: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 6 (SEC-S3L1CG-01, carried from L1c): a composition that fails, or that a cancelled
    start cuts short, closes what it built within `OMS_STOP_RESERVE_S` less the lane's join, the
    bound the cancelled start's wait gives it, so every closer's share fits that wait."""
    reserves, closed, began = list[float](), oms_wiring._closed, asyncio.Event()

    async def timed(closers: Any, deadline: float) -> None:
        reserves.append(deadline - asyncio.get_running_loop().time())
        await closed(closers, deadline)

    async def hangs(self: Sink) -> None:
        began.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(oms_wiring, "_closed", timed)
    world = World(sink_fails=RuntimeError("the WAL is locked") if ends == "failed" else None)
    if ends == "failed":
        async with started(world.runtime()):
            pass
    else:
        monkeypatch.setattr(Sink, "start", hangs)
        start = asyncio.ensure_future(world.runtime().start())
        await asyncio.wait_for(began.wait(), 10)  # a bound on the test, never a time it expects
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start
    reserve = OMS_STOP_RESERVE_S - LANE_JOIN_S
    assert reserves and all(reserve - 1 < share <= reserve for share in reserves)


def test_the_lanes_sink_counts_its_pending_rows_apart_from_the_bundles(tmp_path: Path) -> None:
    """CR-S3L2-04: `cv_machine_event_wal_pending` is labelled by where its sink runs, so the order
    lane's own sink (`pg_stores`) and a persistence bundle's, on the serving loop, each set a
    series of their own, never one they overwrite in turn."""
    metrics = Metrics("demo")
    lane: Any = pg_stores(Settings(), metrics).sink(str(tmp_path / "machine_events.wal"))
    lane._metrics.pending(4)
    PersistOps(metrics).pending(2)  # the bundle's
    text = generate_latest(metrics.registry).decode()
    assert 'cv_machine_event_wal_pending{env="demo",where="order_lane"} 4.0' in text
    assert 'cv_machine_event_wal_pending{env="demo",where="serving_loop"} 2.0' in text


async def test_a_second_process_of_the_environment_fails_closed_critical_and_paged() -> None:
    """SEC-S3N-01 (#913 L2; CR-S3L2-09, one behaviour): another process holds the environment's
    lock, a deploy overlapping on another host: the runtime fails closed before any facade or
    machine exists, logged CRITICAL by its phase and paged once, `degraded`, and is not asked
    again."""
    world = World()
    world.lock.elsewhere = True
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            assert (failed_closed(logs), failed_phases(logs)) == (
                ["EnvironmentLocked"], ["environment_lock"]
            )  # fmt: skip
            closed = [e["log_level"] for e in logs if e["event"] == "oms_runtime_failed_closed"]
            assert closed == ["critical"] and world.lock.wired == [False]
            assert world.pager.calls == ["oms_runtime_failed_closed: environment_lock"]
            assert runtime.state == "degraded" and not b01.ports_wired()
            await settle()
    assert world.lock.wired == [False] and world.lanes[0].stopped  # never asked again


async def test_a_second_process_sweeps_nothing_and_releases_no_lock_it_never_held() -> None:
    """SEC-S3N-01 (CR-S3L2-09, one behaviour): the refused process serves no order and leaves the
    first's unsent entry as it was; it closes its port and its pool and gives up no lock."""
    world = World()
    world.lock.elsewhere = True
    await crashed(world)
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        with pytest.raises(OmsNotReady):
            _ = runtime.submission
    assert world.log == ["pool.release"] and world.venue.ports[0].closed
    assert world.store._orders[UNSENT.id].lifecycle_state == "validated"


async def test_a_lock_postgres_cannot_answer_is_asked_again_with_the_sweeps_backoff() -> None:
    """CR-S3L2-01/02 (20 Sec.6.2): Postgres unreachable when the start asks the environment's lock
    is no other holder: the start returns `starting`, never ready and nothing paged, and asks
    again, the whole composition with it, after the sweep's backoff on the runtime's sleep, each
    attempt closing what it built; once the lock is held the OMS composes, sweeps and is ready,
    the facade built after the lock each time, as before #913 L2 a sweep outlasted the outage."""
    world = World()
    world.lock.fails = [StorageTierUnavailable("unreachable"), StorageTierUnavailable("again")]
    await crashed(world)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            assert runtime.state == "starting"
            with pytest.raises(OmsNotReady):
                _ = runtime.submission
            await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
            assert runtime.state == "ok"
            assert [port.closed for port in world.venue.ports] == [True, True, False]
    first, ceiling = SWEEP_RETRY_S
    asked = [e["retry_s"] for e in logs if e["event"] == "oms_environment_lock_unanswered"]
    assert asked == [first, min(2 * first, ceiling)] and world.clock.slept[:2] == asked
    assert world.lock.wired == [False] * 3 and world.pager.calls == [] and failed_closed(logs) == []
    assert world.log[:2] == ["pool.release", "pool.release"] and world.log[2:5] == STARTED


async def test_another_holder_met_on_a_later_ask_fails_the_runtime_closed_and_pages_once() -> None:
    """CR-S3L2-01/02: asked again, the lock is answered held elsewhere: the runtime fails closed as
    a start refused at once does, paged once, its lane stopped, and asks no more."""
    world = World()
    world.lock.fails, world.lock.elsewhere = [StorageTierUnavailable("unreachable")], True
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: runtime.state == "degraded")
            assert (failed_closed(logs), failed_phases(logs)) == (
                ["EnvironmentLocked"], ["environment_lock"]
            )  # fmt: skip
            assert world.pager.calls == ["oms_runtime_failed_closed: environment_lock"]
            assert world.lanes[0].stopped and not b01.ports_wired()
    assert world.log == ["pool.release", "pool.release"] and len(world.lock.wired) == 2


async def test_a_lane_that_has_not_ticked_within_its_bound_reads_degraded_and_pages_once_a_stall(
) -> None:  # fmt: skip
    """Ruling 2 (the orchestrator's of 2026-10-25 12:22Z; CR-S3L1A-02, OM-D12): a lane alive but
    stuck stops ticking; once its last tick is past `LANE_STALE_S` the runtime reads `degraded`,
    as for a dead lane, and pages the first read of the stall alone; a tick ends the stall, and a
    later one pages again."""
    world = World()
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await runtime.wait_ready()
        await settle()  # the heartbeat's first tick
        world.beats.s += LANE_STALE_S
        assert runtime.state == "ok"  # at the bound: not past it
        world.beats.s += 0.001
        assert [runtime.state for _ in range(3)] == ["degraded"] * 3
        world.beats.tick()
        await settle()
        assert runtime.state == "ok"
        world.beats.s += LANE_STALE_S + 0.001
        assert runtime.state == "degraded"
    assert world.pager.calls == ["oms_lane_stalled"] * 2


#: The Owner the lost-lock tests cancel as: the exits stay open (ruling 3).
_FENCED_OWNER = UUID(int=0x0E)
#: How the watchdog finds the lock lost: its session no longer holds the key, or cannot tell.
LOST = pytest.mark.parametrize("lost", ["released", "unanswered"])


@asynccontextmanager
async def lock_lost(lost: str) -> AsyncIterator[tuple[World, OmsRuntime]]:
    """Ruling 3 (the orchestrator's of 2026-10-25 12:22Z; CR-S3L2-03): a runtime ready after a
    crash, its Owner seeded, whose watchdog then finds on its tick that the lock's session no
    longer holds the key (`released`) or cannot tell (`unanswered`): two ticks, the loss and one
    more. Before the loss the `oms` check is `ok`, the lock was asked once, and the composed
    switches, B1's `SEND`'s too, refuse nothing."""
    world = World()
    await crashed(world)
    for flag in world.flags:
        flag.read()
    world.store.seed_owner(_FENCED_OWNER)
    async with started(world.runtime()) as runtime:
        await runtime.wait_ready()
        await settle()
        assert (runtime.readiness, world.lock.confirms) == ("ok", 1)
        assert runtime._composed().route.switches.refusal(cr.ACCOUNT, "demo") is None
        if lost == "released":
            world.lock.confirmed = False
        else:
            world.lock.unconfirmed = StorageTierUnavailable("no answer")
        for _ in range(2):  # two ticks: the loss, and one more
            world.beats.tick()
            await settle()
        yield world, runtime


@LOST
async def test_a_lost_lock_reads_degraded_pages_once_and_its_watchdog_asks_no_more(
    lost: str,
) -> None:
    """Ruling 3 (CR-S3L2X-06, one behaviour): once the lock is lost the `oms` check reads
    `degraded`, paged once, and the watchdog asks no more, while the state the exit routes read
    stays `ok`."""
    async with lock_lost(lost) as (world, runtime):
        assert (runtime.state, runtime.readiness, _oms_state(runtime)) == (
            "ok", "degraded", "degraded"
        )  # fmt: skip
    assert world.pager.calls == ["oms_environment_lock_lost"] and world.lock.confirms == 2


@LOST
async def test_a_lost_lock_refuses_every_new_submit_oms_not_ready(lost: str) -> None:
    """Ruling 3 (CR-S3L2X-06, one behaviour): the route's task and the pipeline's own entry alike
    are refused `oms_not_ready`."""
    async with lock_lost(lost) as (_, runtime):
        with pytest.raises(OmsNotReady):
            runtime.run(asyncio.sleep(0))
        with pytest.raises(OmsNotReady):
            await runtime.submission.submit(cast(Any, None), cast(Any, None))


@LOST
async def test_a_lost_lock_is_the_composed_switches_refusal(lost: str) -> None:
    """SEC-S3L2-02 (CR-S3L2X-06, one behaviour): a submitter on the lane, past the route and
    `OnLane`, meets the composed switches, B1's `SEND`'s too: `OmsNotReady`."""
    async with lock_lost(lost) as (_, runtime):
        switches = runtime._composed().route.switches
        assert type(switches.refusal(cr.ACCOUNT, "demo")) is OmsNotReady


@LOST
async def test_a_lost_lock_leaves_the_exits_open_so_a_cancel_runs_to_the_venue(lost: str) -> None:
    """Ruling 3 (CR-S3L2X-06, one behaviour): no exit is blocked (C-2.6, C-2.21): the crash's sent
    entry is cancelled, accepted."""
    actor = SubmitActor(user_id=_FENCED_OWNER, role="owner")
    caller = ExitCaller(OwnerScope(_FENCED_OWNER), actor)
    async with lock_lost(lost) as (_, runtime):
        await runtime._composed().machines.settled(
            cr.ACCOUNT, SENDING.id, leaving="submitting", timeout_s=10
        )
        scoped = await runtime.exits.scope(caller, SENDING.id)
        assert isinstance(scoped, ScopedOrder)
        cancelled = await runtime.exits.cancel_admitted(
            scoped.order, actor=actor, reason="user", request_id=None
        )
        assert (cancelled.kind, cancelled.status) == ("accepted", 202)


async def test_a_new_holder_waits_out_the_fencing_grace_before_its_sweep_and_first_admit() -> None:
    """SEC-S3L2-01 (the Fable lens at 864fa082; 20 Sec.6.2): a previous holder whose session ended
    fences itself within a tick and its watchdog's bound, so a process that takes the lock waits
    `ENVIRONMENT_FENCE_GRACE_S` from then before its startup sweep, and so its first admit:
    `starting`, nothing swept, until the grace has run out."""
    world, go = World(), asyncio.Event()
    await crashed(world)
    for flag in world.flags:
        flag.read()

    async def held(seconds: float) -> None:
        world.graces.append(seconds)
        await go.wait()
        world.clock.s += seconds

    async with started(world.runtime(fencing=held)) as runtime:
        await until(lambda: bool(world.graces))
        assert world.graces == [ENVIRONMENT_FENCE_GRACE_S]
        assert ENVIRONMENT_FENCE_GRACE_S == LANE_TICK_S + ENVIRONMENT_LOCK_TIMEOUT_S
        await settle()
        assert runtime.state == "starting" and world.log == STARTED
        assert world.store._orders[UNSENT.id].lifecycle_state == "validated"  # not swept
        go.set()
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
        assert world.store._orders[UNSENT.id].lifecycle_state == "killed"  # swept after it


async def test_step_ones_waits_count_toward_the_fencing_grace() -> None:
    """SEC-S3L2-01: the grace runs from the lock's take, so step 1's waits count toward it, and the
    sweep with its wait still fits a deploy's `/readyz` window: 2 s of polls leave 4 s of it."""
    world = World(standings=SimpleNamespace(read_once=False))
    for flag in world.flags:
        flag.read()

    async def polled(seconds: float) -> None:
        await world.clock.sleep(seconds)
        if len(world.clock.slept) == 8:  # the key standing's first good read, 2 s in
            world.standings.read_once = True

    async with started(world.runtime(sleep=polled)) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
    assert world.clock.slept == [STARTUP_POLL_S] * 8
    assert world.graces == [ENVIRONMENT_FENCE_GRACE_S - 8 * STARTUP_POLL_S]


async def test_the_serving_loop_reads_the_lanes_state_so_a_stall_pages_with_no_reader() -> None:
    """SEC-S3L2-04 (the Fable lens at 864fa082): every `LANE_STALE_S` the serving loop reads the
    runtime's state itself, so a lane alive but unticked past its bound pages with nothing else
    reading it, once a stall."""
    world = World()
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await runtime.wait_ready()
        await settle()  # the heartbeat's first tick
        world.beats.s += LANE_STALE_S + 0.001  # unticked past its bound; no route, no `/readyz`
        for _ in range(2):  # two watches of one stall: one page
            world.watches.tick()
            await settle()
        assert world.pager.calls == ["oms_lane_stalled"]
    assert world.watched and set(world.watched) == {LANE_STALE_S}


async def test_the_serving_loops_watch_pages_a_dead_lane_with_no_reader() -> None:
    """SEC-S3L2-04: the watch reads the state, not the heartbeat alone, so a lane whose loop has
    died, which ticks no more either, pages as dead, once, with nothing else reading it."""
    world = World()
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await runtime.wait_ready()
        world.lanes[-1].dead = True
        for _ in range(2):
            world.watches.tick()
            await settle()
        assert world.pager.calls == ["oms_lane_died"]


async def test_a_watch_that_ends_on_an_error_is_logged_critical_and_paged() -> None:
    """SEC-S3L2-04 (CR-S3L2X-02): the serving loop's watch ended other than by the stop's cancel
    leaves a dead or wedged lane unpaged until something reads the state: logged CRITICAL by its
    error's class and paged at once."""
    world = World()

    async def broken(seconds: float) -> None:
        raise RuntimeError("the watch broke")

    with capture_logs() as logs:
        async with started(world.runtime(watch=broken)):
            await settle()
            assert world.pager.calls == ["oms_lane_watch_ended"]
    ended = [(e["log_level"], e["error"]) for e in logs if e["event"] == "oms_lane_watch_ended"]
    assert ended == [("critical", "RuntimeError")]


async def test_the_stop_cancels_the_serving_loops_watch() -> None:
    """SEC-S3L2-04 (CR-S3L2X-02): the watch runs from the start to the stop, which cancels it, so
    no read of a stopped runtime's state follows."""
    world = World()
    async with started(world.runtime()) as runtime:
        watch = runtime._watching
        assert watch is not None and not watch.done()
    assert watch.cancelled() and runtime._watching is None


async def test_a_heartbeat_that_ends_on_an_error_is_logged_critical_and_paged() -> None:
    """SEC-S3L2-04: a heartbeat that ends other than by its stop's cancel leaves the lane unticked
    and its lock unwatched: logged CRITICAL by its error's class and paged at once, before any
    read finds the lane stalled."""
    world = World()

    class Broken(Heart):
        async def run(self) -> None:
            raise RuntimeError("the heartbeat broke")

    def broken(lock: Any, pager: Any) -> Heart:
        return Broken(lock, pager, world.beats, world.log)

    with capture_logs() as logs:
        async with started(world.runtime(heartbeat=broken)):
            await settle()
            assert world.pager.calls == ["oms_lane_heartbeat_ended"]
    ended = [(e["log_level"], e["error"]) for e in logs if e["event"] == "oms_lane_heartbeat_ended"]
    assert ended == [("critical", "RuntimeError")]


async def test_the_fifth_unanswered_ask_of_the_lock_pages_once_and_the_asking_goes_on() -> None:
    """SEC-S3L2-06 (the Fable lens at 864fa082): Postgres out at the start is no other holder, so
    the runtime asks the lock again for as long as it takes; the `SWEEP_MAX_FAILURES`-th
    unanswered ask in a row, the start's own counted, is logged CRITICAL and paged, once, and the
    asking goes on until the lock is held and the runtime ready."""
    world = World()
    world.lock.fails = [StorageTierUnavailable("out") for _ in range(SWEEP_MAX_FAILURES + 1)]
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
    asked = [e["log_level"] for e in logs if e["event"] == "oms_environment_lock_unanswered"]
    assert asked == ["warning"] * (SWEEP_MAX_FAILURES - 1) + ["critical", "warning"]
    assert world.pager.calls == ["oms_environment_lock_unanswered"]
    assert len(world.lock.wired) == SWEEP_MAX_FAILURES + 2  # every ask, the held one last


async def test_the_asked_again_locks_backoff_doubles_to_the_sweeps_ceiling_and_stays_there() -> (
    None
):
    """CR-S3L2-02 (CR-S3L2X-04; 20 Sec.6.2): between the asks of a lock Postgres cannot answer the
    runtime sleeps the sweep's backoff, 1 s doubling to 30 s, then 30 s each time."""
    world = World()
    world.lock.fails = [StorageTierUnavailable("out") for _ in range(7)]
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
    assert SWEEP_RETRY_S == (1.0, 30.0)
    assert world.clock.slept == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


async def test_a_stop_that_begins_as_the_composition_ends_takes_and_closes_what_it_composed(
) -> None:  # fmt: skip
    """SEC-S3L2-05 (the Fable lens at 864fa082): a stop that begins as the lock's asked-again
    composition ends cancels the startup task before it resumes with what was composed; the
    composition handed it to the runtime under the lock the stop takes, so the stop closes it,
    never leaves it open."""
    world, stops = World(), list[asyncio.Task[None]]()
    world.lock.fails = [StorageTierUnavailable("out")]  # the startup task composes again

    def beat(lock: Any, pager: Any) -> Heart:  # the composition's last step
        stops.append(asyncio.ensure_future(runtime.stop()))
        return world.heartbeat(lock, pager)

    runtime = world.runtime(heartbeat=beat)
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        await runtime.start()
        await until(lambda: bool(stops))
        await asyncio.wait_for(stops[0], 10)  # a bound on the test
        assert runtime._parts is None and not b01.ports_wired()
        assert world.log == ["pool.release", *STARTED, *STOPPED]
    finally:
        b01._ATTEMPTS = saved


async def test_a_composition_that_meets_a_begun_stop_closes_what_it_built_itself() -> None:
    """SEC-S3L2-05: a stop that began on the serving loop while the lane composed is seen by the
    composition as it ends: it closes what it built itself and ends cancelled, so the stop has
    nothing left to close and nothing is closed twice."""
    world = World()
    world.lock.fails = [StorageTierUnavailable("out")]

    def beat(lock: Any, pager: Any) -> Heart:  # the stop's first step, from the serving thread
        runtime._stopping = True
        return world.heartbeat(lock, pager)

    runtime = world.runtime(heartbeat=beat)
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        await runtime.start()
        startup = runtime._startup
        assert startup is not None
        await until(startup.done)
        assert startup.cancelled() and runtime._parts is None and not b01.ports_wired()
        assert world.log == ["pool.release", *STARTED, *STOPPED]
        await runtime.stop()
        assert world.log == ["pool.release", *STARTED, *STOPPED]
    finally:
        b01._ATTEMPTS = saved


async def test_a_start_cancelled_as_its_composition_ends_closes_what_was_handed_over() -> None:
    """SEC-S3L2-05: a start cancelled once its composition has ended, before it resumes, finds
    what was composed handed to the runtime and closes it before it stops the lane."""
    world, starts = World(), list[asyncio.Task[None]]()

    def beat(lock: Any, pager: Any) -> Heart:
        starts[0].cancel()  # as the composition ends
        return world.heartbeat(lock, pager)

    runtime = world.runtime(heartbeat=beat)
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        starts.append(asyncio.ensure_future(runtime.start()))
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(starts[0], 10)  # a bound on the test
        assert runtime._parts is None and not b01.ports_wired()
        assert world.log == [*STARTED, *STOPPED] and world.lanes[0].stopped
    finally:
        b01._ATTEMPTS = saved


async def test_a_start_a_stop_overtook_as_its_composition_ended_spawns_nothing() -> None:
    """SEC-S3L2-05 (CR-S3L2X-02): a stop that begins as the start's own composition hands its
    parts over takes and closes them before the start resumes, so the start spawns neither the
    startup task nor the serving loop's watch: nothing is asked again or swept after the stop."""
    world, stops = World(), list[asyncio.Task[None]]()

    def beat(lock: Any, pager: Any) -> Heart:  # the composition's last step: a stop begins
        stops.append(asyncio.ensure_future(runtime.stop()))
        return world.heartbeat(lock, pager)

    runtime = world.runtime(heartbeat=beat)
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        await runtime.start()
        await asyncio.wait_for(stops[0], 10)  # a bound on the test
        assert (runtime._startup, runtime._watching) == (None, None)
        assert world.log == [*STARTED, *STOPPED] and len(world.lock.wired) == 1
    finally:
        b01._ATTEMPTS = saved


async def test_what_the_asked_again_composition_meets_once_a_stop_began_is_the_stops() -> None:
    """SEC-S3L2-05 (CR-S3L2X-02): once a stop has begun, a failure the lock's asked-again
    composition then meets, the stop's cancel or its stopped lane, ends the startup task
    cancelled: nothing fails closed or pages."""
    world = World()
    world.lock.fails = [StorageTierUnavailable("out")]  # the startup task composes again

    def stopped(lock: Any, pager: Any) -> Heart:  # a stop begun, then its lane stopped under it
        runtime._stopping = True
        raise LaneStopped("the order lane is not running")

    runtime = world.runtime(heartbeat=stopped)
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    try:
        with capture_logs() as logs:
            await runtime.start()
            startup = runtime._startup
            assert startup is not None
            await until(startup.done)
        assert startup.cancelled() and (failed_closed(logs), world.pager.calls) == ([], [])
        await runtime.stop()
    finally:
        b01._ATTEMPTS = saved


def test_the_heartbeats_bounds_fit_a_tick_and_a_probe_and_a_lanes_own_read() -> None:
    """Ruling 2: a stall reads only past a tick and the watchdog's bound, so a slow probe is not a
    wedged lane, and within a lane read's own bound (`HOP_TIMEOUT_S`)."""
    assert LANE_TICK_S + ENVIRONMENT_LOCK_TIMEOUT_S < LANE_STALE_S <= HOP_TIMEOUT_S


async def test_a_watchdog_probe_that_never_answers_is_a_lock_lost_at_its_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3L2-03 (CR-S3L2X-04): the watchdog asks within `ENVIRONMENT_LOCK_TIMEOUT_S`, 5 s (20
    Sec.6.2), so a session that never answers is a lock lost at that bound, logged CRITICAL as a
    timeout and paged once, never a tick that waits on it for good. The bound is made 0 here, so
    it passes at once, on the loop's own clock."""
    assert ENVIRONMENT_LOCK_TIMEOUT_S == 5.0
    monkeypatch.setattr(oms_wiring, "ENVIRONMENT_LOCK_TIMEOUT_S", 0.0)

    class Silent(Lock):
        async def confirm(self) -> bool:
            self.confirms += 1
            await asyncio.Event().wait()  # the session never answers
            return True

    lock, beats, pager = Silent(), Beats(), Pager()
    heart = LaneHeartbeat(lock, pager, clock=beats.clock, wait=beats.wait)
    with capture_logs() as logs:
        beating = asyncio.ensure_future(heart.run())
        try:
            await until(lambda: heart.fenced)
        finally:
            beating.cancel()
            await asyncio.wait({beating})
    lost = [(e["log_level"], e["error"]) for e in logs if e["event"] == "oms_environment_lock_lost"]
    assert (lost, pager.calls, lock.confirms) == (
        [("critical", "TimeoutError")], ["oms_environment_lock_lost"], 1
    )  # fmt: skip


def test_the_environments_lock_key_is_its_namespace_and_name_outside_any_hashtext_key() -> None:
    """SEC-S3N-01: one key per environment, BLAKE2b's first 8 bytes over the namespace and the
    environment, outside the 32-bit range of every `hashtext` key (the chain's, the migrations'),
    which `pg_stores` locks on the OMS pool."""
    keys = {env: oms_wiring.environment_lock_key(env) for env in ("live", "demo", "testnet")}
    assert len(set(keys.values())) == 3
    for env, key in keys.items():
        digest = hashlib.blake2b(b"cv.oms.environment:" + env.encode(), digest_size=8).digest()
        assert key == int.from_bytes(digest, "big", signed=True)
        assert not -(2**31) <= key < 2**31
    lock = pg_stores(Settings(environment=Env("demo")), Metrics("demo")).lock
    assert isinstance(lock, SqlAlchemySessionLock) and lock._key == keys["demo"] and not lock.held


async def test_a_composition_that_fails_late_closes_what_it_built_and_fails_closed() -> None:
    """The sink's start refuses (another process holds its WAL): the facade is unwired again and
    the port and the pool closed; the runtime serves no order."""
    world = World(sink_fails=RuntimeError("the WAL is locked"))
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            assert failed_closed(logs) == ["RuntimeError"] and not b01.ports_wired()
            assert world.log == [*STARTED, "audit.stop", "pool.release", "lock.release"]
            assert world.venue.ports[0].closed
            assert world.pager.calls == ["oms_runtime_failed_closed: sink_start"]
            assert failed_phases(logs) == ["sink_start"]
            assert world.pager.severities == ["page"] and world.lanes[0].stopped
            with pytest.raises(OmsNotReady):
                _ = runtime.anchors
            with pytest.raises(OmsNotReady):
                _ = runtime.exits
            with pytest.raises(OmsNotReady):
                _ = runtime.cancel_all


async def test_one_facade_per_process_stop_unwires_it_and_a_second_start_works() -> None:
    """Finding 3: the facade wires B1's process-wide ports, so a second one is refused while the
    first holds them; `stop()` unwires them, and the next `start()` builds a new one."""
    world = World()
    runtime = world.runtime()
    async with started(runtime):
        first = runtime._composed().machines
        with capture_logs() as logs:
            async with started(World().runtime()):
                pass
        assert failed_closed(logs) == ["RuntimeError"]  # the first holds B1's ports (C-2.11)
        assert failed_phases(logs) == ["facade"]
        assert b01.ports_wired()  # the refused one closed what it built, never the first's
    assert not b01.ports_wired()
    async with started(runtime):
        assert b01.ports_wired() and runtime._composed().machines is not first
    assert world.log.count("pool.release") == 2 and all(p.closed for p in world.venue.ports)


async def test_the_facade_takes_the_bundles_latch_so_a_chain_trip_refuses_its_commands() -> None:
    """Round-1 security-4 (C-2.21), CR-S3E1-01: a restore latches into the persistence bundle's
    latch, so the facade must consult that one: tripping it refuses the order's commands."""
    world = World()
    bundle = SimpleNamespace(sink=InMemoryMachineEventSink(), latch=ChainTripLatch())
    async with started(world.runtime(bundle=bundle)) as runtime:
        machines, order = runtime._composed().machines, order_of(1)
        await machines.start(order, environment="demo", gates=GATES)
        bundle.latch.latch(MachineKey("order", str(order.id), "demo"), "chain_trips")
        with pytest.raises(DegradedLatchError):
            await machines.command(ACCOUNT, order.id, "CANCEL", actor="user")


async def test_a_page_that_cannot_be_raised_is_logged_and_the_start_still_fails_closed() -> None:
    """CR-S3E1-02: the pager is down, which loses the page and nothing else."""
    world = World()
    world.pager.refuse = True
    with capture_logs() as logs:
        async with started(world.runtime("live", live_on=True)):
            assert failed_closed(logs) == ["NoMachineEventSink"]
    assert [e["error"] for e in logs if e["event"] == "oms_pager_failed"] == ["RuntimeError"]


@pytest.mark.parametrize("step", ["port", "stores"])
async def test_a_failure_once_the_trading_port_exists_closes_it(
    step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-S3E1-05: the port is registered for closing the moment it is built, so the router or
    the stores (a bad DSN) failing after it leaves it open to no one; no pool exists to close."""
    world = World()

    def refuse(*_args: Any) -> Any:
        raise ValueError("refused")

    over: dict[str, Any] = {}
    if step == "stores":
        over["stores"] = refuse
    else:
        monkeypatch.setattr(world.venue, "lane_waits", refuse)
    with capture_logs() as logs:
        async with started(world.runtime(**over)):
            [port] = world.venue.ports
            assert (failed_closed(logs), failed_phases(logs)) == (["ValueError"], [step])
            assert port.closed and world.log == [] and world.lanes[0].stopped


async def test_a_testnet_process_fails_closed_over_the_real_adapter_that_has_no_testnet_port() -> (
    None
):
    """CR-S3E1-03, ruling R6: the adapter has no trading capability record for testnet, which
    CONSTITUTION.md limits to connectivity smoke tests, so a testnet process fails closed at the
    port with nothing built. The fake venue's port accepts testnet, so this runs the real one."""
    world = World()
    real = ExchangeBybitService(credentials=fake_capability(), environment="testnet")
    with capture_logs() as logs:
        async with started(world.runtime("testnet", venue=real)) as runtime:
            assert (failed_closed(logs), failed_phases(logs)) == (["ValueError"], ["port"])
            assert world.log == [] and not b01.ports_wired() and runtime.state == "degraded"
            assert world.lanes[0].stopped
            with pytest.raises(OmsNotReady):
                _ = runtime.submission


def test_the_fake_backend_composes_no_oms_runtime() -> None:
    """20 Sec.6.2: no runtime, so `placeOrder` answers `501 not_implemented` there."""
    names = ("metrics", "gate", "standings", "oms_enabled", "live_enabled")
    unused = dict.fromkeys((*names, "profiles", "persistence", "feed"))
    assert build_oms_runtime(cast(Any, None), Settings(), **cast(Any, unused)) is None


async def test_the_state_is_starting_while_the_startup_runs_and_degraded_once_failed_closed() -> (
    None
):
    world = World()
    async with started(world.runtime()) as runtime:
        assert (runtime.started, runtime.state) == (True, "starting")  # waiting on the flags
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        world.lanes[0].dead = True  # its thread's loop ended (CR-S3L1A-02)
        assert runtime.state == "degraded"
    assert not runtime.started
    async with started(world.runtime("live", live_on=True)) as runtime:
        assert (runtime.started, runtime.state) == (True, "degraded")  # no bundle: never ready


async def test_a_dead_lane_pages_once_per_death_however_often_its_state_is_read() -> None:
    """SEC-S3L1A-02: the runtime pages its lane's death as it does its other fail-closed
    transitions, the first time it reads it, and never again; the next start's lane, dying, pages
    once more."""
    world = World()
    runtime = world.runtime()
    for _ in range(2):
        async with started(runtime):
            world.lanes[-1].dead = True
            assert [runtime.state for _ in range(3)] == ["degraded"] * 3
    assert (world.pager.calls, world.pager.severities) == (["oms_lane_died"] * 2, ["page"] * 2)


async def test_the_startup_waits_out_its_bound_for_the_clock_and_keys_then_for_both_flags() -> None:
    """20 Sec.6.2 step 1: at most `CV_OMS_STARTUP_WAIT_S` for the clock guard's first measurement
    and the key standing's first good read, then on; the flags' first read, however long."""
    world = World(standings=SimpleNamespace(read_once=False))
    world.ingestion.clock = FakeClockHealth(world.clock)  # never measured
    with capture_logs() as logs:
        async with started(world.runtime()):
            await until(lambda: sum(world.clock.slept) >= Settings().oms_startup_wait_s)
            await settle()
            assert sum(world.clock.slept) == Settings().oms_startup_wait_s  # and no further
            world.flags[0].read()
            await settle()
            assert "oms_startup_waited" not in [e["event"] for e in logs]
            world.flags[1].read()
            await settle()
    [waited] = [e for e in logs if e["event"] == "oms_startup_waited"]
    assert (waited["clock"], waited["keys_read"]) == ("unmeasured", False)


async def test_the_startup_does_not_wait_once_measured_and_read() -> None:
    world = World()
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()):
            await settle()
    assert world.clock.slept == []
    [waited] = [e for e in logs if e["event"] == "oms_startup_waited"]
    assert (waited["clock"], waited["keys_read"]) == ("measured", True)


async def test_stop_drains_the_submits_for_cv_oms_drain_s_then_cancels_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 Sec.8.4 step 12, 20 Sec.6.2: a submit that ends within the drain keeps its answer; one
    still running when the drain's bound is spent is cancelled, as the startup task is."""
    drains: list[float] = []
    drained = oms_wiring._drained

    async def spent(tasks: set[asyncio.Task[Any]], timeout_s: float) -> set[asyncio.Task[Any]]:
        drains.append(timeout_s)
        return await drained(tasks, 0)  # the bound, spent at once

    monkeypatch.setattr(oms_wiring, "_drained", spent)
    world = World()
    async with started(world.runtime()) as runtime:
        answered = runtime.run(asyncio.sleep(0, result="202"))
        hung = runtime.run(asyncio.Event().wait())
        await answered
        startup = runtime._startup
    assert drains == [Settings().oms_drain_s] and answered.result() == "202"
    assert hung.cancelled() and startup is not None and startup.cancelled()


async def test_run_refuses_once_the_stop_began_and_closes_the_coroutine() -> None:
    world = World()
    async with started(world.runtime()) as runtime:
        pass
    late = asyncio.sleep(0)
    with pytest.raises(OmsNotReady):
        runtime.run(late)
    assert inspect.getcoroutinestate(late) == inspect.CORO_CLOSED


async def test_run_refuses_a_submit_from_another_event_loop() -> None:
    """CR-S3C2-01: the facade and its state feed live on the loop that started the runtime (the
    lifespan's, the serving loop), so a submit from any other loop is refused."""
    world = World()
    async with started(world.runtime()) as runtime:

        def elsewhere() -> None:
            async def submit() -> None:
                runtime.run(asyncio.sleep(0))

            asyncio.run(submit())

        with pytest.raises(RuntimeError, match="CR-S3C2-01"):
            await asyncio.to_thread(elsewhere)


async def test_run_before_any_start_or_after_a_failed_one_is_not_ready_and_closes_it() -> None:
    """CR-S3E2-06: a route that skipped its readiness check answers 503, not a RuntimeError 500."""
    never, failed = asyncio.sleep(0), asyncio.sleep(0)
    with pytest.raises(OmsNotReady):
        World().runtime().run(never)
    async with started(World().runtime("live", live_on=True)) as runtime:  # fails closed
        with pytest.raises(OmsNotReady):
            runtime.run(failed)
    assert {inspect.getcoroutinestate(c) for c in (never, failed)} == {inspect.CORO_CLOSED}


async def test_on_a_stopped_or_unanswering_lane_the_routes_calls_are_not_ready() -> None:
    """CR-S3L1B-07, CR-S3L1A-02: a lane that stopped meanwhile, or that has not answered a read
    within `HOP_TIMEOUT_S`, is `OmsNotReady` (503 `oms_not_ready`), not a 500; the submit has no
    hop bound (its bound is the stop's drain), so the lane's timeout is not one it gets."""

    async with started(World().runtime()) as runtime:
        parts, nothing = runtime._composed(), cast(Any, None)
        for error in (LaneStopped("stopped"), TimeoutError()):
            on_lane = oms_wiring.OnLane(replace(parts, lane=(lane := Refusing(error))))
            with pytest.raises(OmsNotReady):
                await on_lane.environment_of(cr.ACCOUNT)
            with pytest.raises(OmsNotReady if isinstance(error, LaneStopped) else TimeoutError):
                await on_lane.submit(nothing, nothing)
            assert lane.bounds == [HOP_TIMEOUT_S, None]


async def test_the_exit_routes_reach_the_exit_service_on_the_lane() -> None:
    """#913 slice 4 on the lane (the orchestrator's ruling of 2026-10-25 02:34Z): `runtime.exits`
    hops each of the exit service's calls to the order lane, where its store and B1's facade run,
    a read within `HOP_TIMEOUT_S`; the route's own task stays on the serving loop."""
    lane = Recording()
    async with started(World().runtime(lane=lambda: lane)) as runtime:
        exits = runtime.exits
        assert isinstance(exits, oms_wiring.OnLaneExits)
        lane.hops.clear()
        owner = SubmitActor(user_id=UUID(int=1), role="owner")
        got = await exits.scope(ExitCaller(OwnerScope(UUID(int=1)), owner), UUID(int=7))
        assert got.status == 404  # no such order: nothing recorded, nothing else read
        assert lane.hops == [("OrderExits.scope", HOP_TIMEOUT_S)]


async def test_on_a_stopped_or_unanswering_lane_the_exit_service_is_not_ready() -> None:
    """As the submit's (CR-S3L1B-07): a lane that stopped is `OmsNotReady` for each of the exit
    service's calls, unrun; its reads are bounded by `HOP_TIMEOUT_S` and `OmsNotReady` past it,
    while a refusal's record, a cancel and an amend wait out the service's own bounds, so the
    lane's timeout is not one they get."""
    async with started(World().runtime()) as runtime:
        parts, nothing = runtime._composed(), cast(Any, None)
        for error in (LaneStopped("stopped"), TimeoutError()):
            exits = oms_wiring.OnLaneExits(replace(parts, lane=(lane := Refusing(error))))
            with pytest.raises(OmsNotReady):
                await exits.scope(nothing, UUID(int=7))
            with pytest.raises(OmsNotReady):
                await exits.accounts_in_scope(nothing, ())
            written = OmsNotReady if isinstance(error, LaneStopped) else TimeoutError
            with pytest.raises(written):
                await exits.deny(nothing, "cancel", nothing, actor=nothing, request_id=None)
            with pytest.raises(written):
                await exits.cancel_admitted(nothing, actor=nothing, reason="user", request_id=None)
            with pytest.raises(written):
                await exits.amend(nothing, nothing, caller=nothing, expected_seq=None)
            assert lane.bounds == [HOP_TIMEOUT_S, HOP_TIMEOUT_S, None, None, None]


async def test_the_lanes_deny_carries_an_exit_routes_step_to_the_exit_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 Sec.8.4 and 15.5: an exit route records each refusal it makes through `deny`, naming its
    step (the cancel's `key`, `replay` and `guard`, as `placeOrder`'s records do) and, where it has
    one, its reason, so the lane's hop carries the row, the operation, the refusal and every named
    argument to the exit service unchanged, unbounded as a refusal's record is."""
    lane = Recording()
    async with started(World().runtime(lane=lambda: lane)) as runtime:
        refusal = ExitOutcome(kind="refused", status=409, code="conflict")
        seen = list[tuple[tuple[Any, ...], dict[str, Any]]]()

        async def deny(*args: Any, **kwargs: Any) -> ExitOutcome:
            seen.append((args, kwargs))
            return refusal

        monkeypatch.setattr(runtime._composed().exits, "deny", deny)
        lane.hops.clear()
        row, actor, request_id = cast(Any, object()), cast(Any, object()), UUID(int=9)
        got = await runtime.exits.deny(
            row, "amend", refusal, actor=actor, request_id=request_id, step="class",
            reason="reclassified",
        )  # fmt: skip
        assert got is refusal
        named = {"actor": actor, "request_id": request_id, "step": "class"}
        named["reason"] = "reclassified"
        assert seen == [((row, "amend", refusal), named)]
        assert [bound for _, bound in lane.hops] == [None]


async def test_the_exit_routes_in_flight_guard_is_read_in_place_and_theirs_alone() -> None:
    """20 Sec.6.2's read in place: the routes' `run_claimed` claims and releases the in-flight guard
    on the serving loop, and the exit service never touches it after building it."""
    async with started(World().runtime()) as runtime:
        assert runtime.exits.guard is runtime._composed().exits.guard
    source = inspect.getsource(OrderExits)
    assert source.count("self.guard") == 1 and "self.guard = InFlightGuard()" in source


async def test_cancel_all_reaches_its_service_on_the_lane() -> None:
    """#913 S4-E over the order lane (the orchestrator's ruling of 2026-10-25 06:41Z):
    `runtime.cancel_all` hops the cancel-all service's calls to the lane, where the service, the
    exit service and the order store run. Its scope, a read, hops within `HOP_TIMEOUT_S`; its run,
    which the service's own deadline bounds, hops without one. The route's task stays on the serving
    loop."""
    lane = Recording()
    async with started(World().runtime(lane=lambda: lane)) as runtime:
        cancel_all = runtime.cancel_all
        assert isinstance(cancel_all, oms_wiring.OnLaneCancelAll)
        lane.hops.clear()
        every = CancelAllRequest(exchange_account_ids=(), symbol=None, intents=frozenset())
        scoped = await cancel_all.scope(OwnerScope(UUID(int=1)), every)
        owner = SubmitActor(user_id=UUID(int=1), role="owner")
        await cancel_all.run(scoped, every, actor=owner, request_id=None)
        assert lane.hops == [("CancelAll.scope", HOP_TIMEOUT_S), ("CancelAll.run", None)]


async def test_on_a_stopped_or_unanswering_lane_cancel_all_is_not_ready() -> None:
    """As the exit service's (CR-S3L1B-07): a lane that stopped is `OmsNotReady` for each of the
    cancel-all service's calls, unrun. Its scope's read is bounded by `HOP_TIMEOUT_S`, `OmsNotReady`
    past it, while its run waits out the service's own deadline, so the lane's timeout is not one it
    gets."""
    async with started(World().runtime()) as runtime:
        parts, nothing = runtime._composed(), cast(Any, None)
        for error in (LaneStopped("stopped"), TimeoutError()):
            cancel_all = oms_wiring.OnLaneCancelAll(replace(parts, lane=(lane := Refusing(error))))
            with pytest.raises(OmsNotReady):
                await cancel_all.scope(nothing, nothing)
            with pytest.raises(OmsNotReady if isinstance(error, LaneStopped) else TimeoutError):
                await cancel_all.run(nothing, nothing, actor=nothing, request_id=None)
            assert lane.bounds == [HOP_TIMEOUT_S, None]


async def test_a_202s_etag_reads_the_order_facades_versions_in_place_never_on_the_lane() -> None:
    """20 Sec.6.2's read in place (ruling Q5, the orchestrator's Q8 ruling): the route's `versions`
    is B1's facade itself, whose `version()` a `202`'s `ETag` reads from the serving loop with no
    hop to the lane, a single read of the order's view, which each committed step replaces whole
    (`_stepped`) and nothing writes in place."""
    lane = Recording()
    async with started(World().runtime(lane=lambda: lane)) as runtime:
        lane.hops.clear()
        versions = runtime.route.versions
        assert versions is runtime._composed().machines
        assert versions.version(UUID(int=7)) is None  # no such order, so no version
        assert lane.hops == []
    assert not inspect.iscoroutinefunction(OrderMachines.version)
    source = inspect.getsource(OrderMachines)
    in_place = re.compile(r"\.view(\[|\.(update|pop|popitem|setdefault|clear)\()")
    assert source.count(".view = {") == 1 and not in_place.search(source)


async def test_an_error_out_of_the_startup_task_is_logged_with_its_type() -> None:
    """CR-S3E2-07: a flag view that raises ends the startup task, leaving `degraded`; the log says
    why, instead of asyncio's "never retrieved" at garbage collection."""

    class Unreadable(Flag):
        async def first_read(self) -> None:
            raise RuntimeError("the flag store is down")

    world = World()
    with capture_logs() as logs:
        async with started(world.runtime(oms_enabled=Unreadable())) as runtime:
            await until(lambda: runtime.state == "degraded")
            await settle()
    assert [e["error"] for e in logs if e["event"] == "oms_startup_failed"] == ["RuntimeError"]


async def test_stop_gives_each_closer_its_share_so_one_that_fails_or_hangs_starves_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3E2-04: each close step is isolated and has its share of `OMS_STOP_RESERVE_S`. The
    command port fails to close and the sink's drain never ends; the trading port, which needs a
    turn of the loop, and the pool still close, and the whole stop is bounded."""
    # 12 closers share 0.5 s (the reserve less the lane's join): the drain's cancel, the lane's
    # wait, the exits, the stop gate (CR-S3H3B-01), the machines, the commands, then the hung sink,
    # which costs a sixth of what is left, the lane's audit writer (#913 L2), the trading port,
    # the pool, the lane's heartbeat and the environment's lock (SEC-S3N-01)
    monkeypatch.setattr(oms_wiring, "OMS_STOP_RESERVE_S", 1.5)

    async def fails(self: OmsCommandPort) -> None:
        raise RuntimeError("the resync would not end")

    async def hangs(self: Sink) -> None:
        await asyncio.Event().wait()

    async def settles(self: Port) -> None:
        await asyncio.sleep(0)
        self.closed = True

    monkeypatch.setattr(OmsCommandPort, "aclose", fails)
    monkeypatch.setattr(Sink, "stop", hangs)
    monkeypatch.setattr(Port, "aclose", settles)
    world = World()
    with capture_logs() as logs:
        async with asyncio.timeout(10), started(world.runtime()):  # 10 s: a bound on the test
            pass
    steps = [(e["step"], e["error"]) for e in logs if e["event"] == "oms_stop_step_failed"]
    assert steps == [("commands", "RuntimeError"), ("sink", "TimeoutError")]
    assert world.venue.ports[0].closed
    assert world.log == [*STARTED, "audit.stop", "pool.release", "heartbeat.end", "lock.release"]
    assert not b01.ports_wired()  # the facade, first in line, closed too


async def test_a_cancelled_stop_still_stops_the_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-S3L1B-03: the stop is cancelled while the sink's drain hangs; the lane still stops."""
    world, began = World(), asyncio.Event()

    async def hangs(self: Sink) -> None:
        began.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(Sink, "stop", hangs)
    runtime = world.runtime()
    await runtime.start()
    stop = asyncio.ensure_future(runtime.stop())
    await began.wait()
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    assert world.lanes[0].stopped


class Composing(InlineLane):
    """A lane holding the compose, closed unrun, on a future of its own, as `OrderLane` answers a
    call: its caller's cancel ends that wait at once. The wait for the compose's unwind there is
    refused, the lane dead by then, or never ends."""

    def __init__(self, dead: bool) -> None:
        super().__init__()
        self.dead = dead

    def call[T](
        self, coro: Coroutine[Any, Any, T], *, timeout_s: float | None = None
    ) -> asyncio.Future[T]:
        coro.close()
        return asyncio.get_running_loop().create_future()

    async def idle(self) -> None:
        if self.dead:
            raise LaneStopped("the order lane is not running")
        await asyncio.Event().wait()


@pytest.mark.parametrize("dead", [True, False], ids=["dead", "unwinding"])
async def test_a_cancelled_start_stops_its_lane_dead_or_unwinding_and_stays_cancelled(
    monkeypatch: pytest.MonkeyPatch, dead: bool
) -> None:
    """CR-S3L1C-02/-06: the start, cancelled as it awaits the compose on the lane, waits there for
    the compose's unwind within the stop reserve less the join's share, none here. A lane dead by
    then, or an unwind past that bound, still has the lane stopped, and the caller gets the start's
    own cancellation, never that error."""
    for name in ("OMS_STOP_RESERVE_S", "LANE_JOIN_S"):  # the reserve all the join's
        monkeypatch.setattr(oms_wiring, name, 60.0)
    lane = Composing(dead)
    start = asyncio.ensure_future(World().runtime(lane=lambda: lane).start())
    await settle()
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(10):  # a bound on the test: the whole reserve outlasts it
            await start
    assert lane.stopped


async def test_drained_returns_at_once_when_its_tasks_end_inside_the_bound() -> None:
    """CR-S3E2-08: `_drained` itself. A task that `call_soon` ends is awaited, not waited out: the
    1 s bound is nowhere near spent; a task that never ends is what remains once the bound is."""
    loop, done = asyncio.get_running_loop(), asyncio.Event()
    ends, never = asyncio.create_task(done.wait()), asyncio.create_task(asyncio.Event().wait())
    loop.call_soon(done.set)
    began = loop.time()
    assert await oms_wiring._drained({ends}, 1.0) == set()
    assert loop.time() - began < 0.5
    assert await oms_wiring._drained({never}, 0) == {never}
    never.cancel()
    await asyncio.gather(never, return_exceptions=True)


@pytest.mark.parametrize(
    ("state", "checks"),
    [
        ("ok", [{"name": "oms", "ok": True, "detail": ""}]),
        ("starting", [{"name": "oms", "ok": False, "detail": "starting"}]),
        ("degraded", [{"name": "oms", "ok": False, "detail": "degraded"}]),
        (None, []),
    ],
)
def test_readyz_gives_the_runtimes_state_alone_while_it_runs(
    state: str | None, checks: list[dict[str, Any]]
) -> None:
    """20 Sec.6.2: `/readyz` is anonymous, so the check names no posture; none while stopped."""
    app = FastAPI()
    app.include_router(make_health_router(Settings(), oms_state=lambda: state))
    body = TestClient(app).get("/readyz").json()
    assert (body["status"], body["checks"]) == (
        "ok" if state in (None, "ok") else "degraded",
        checks,
    )


# --- the startup sweep (20 Sec.6.2 steps 2 to 5) --------------------------------------------------

KEY = UUID(int=0xBEEF)
UNSENT, SENDING = cr.new_order(seq=1), cr.new_order(seq=2)
LIVE_UNSENT = cr.new_order(cr.LIVE_ACCOUNT, "live", seq=3)
DEMO_TWO = AccountId(UUID(int=0xD2))


def _attach_rows(order: NewOrder, first: int = 11) -> list[NewRecordedStop]:
    """The entry's attach rows as its first persist records them: its stop-loss and take-profit,
    with ids from `first` on."""
    common: dict[str, Any] = {
        "exchange_account_id": order.exchange_account_id, "symbol": order.symbol,
        "position_idx": 0, "position_side": "Buy", "source": "entry_attach",
        "order_id": order.id, "tpsl_mode": "Full", "size": None, "actor_user_id": None,
    }  # fmt: skip
    return [
        NewRecordedStop(
            id=UUID(int=first), kind="stop_loss", trigger_price=cr.STOP,
            audit_record_id=UUID(int=first + 1), **common,
        ),
        NewRecordedStop(
            id=UUID(int=first + 2), kind="take_profit", trigger_price=Decimal(64000),
            audit_record_id=UUID(int=first + 3), **common,
        ),
    ]  # fmt: skip


async def _written(_rows: tuple[RecordedStopRow, ...]) -> None:
    return None


async def crashed(world: World, *, deleted: bool = False, live: bool = False) -> None:
    """A process that went down leaving two entries of the demo account, as a crash leaves them:
    `UNSENT` recorded and never sent, its attach rows pending, and `SENDING`, its create at the
    venue's door; its facade stopped, its attempts gone with its memory. With `live`, a live
    account's entry, `LIVE_UNSENT`, is recorded and unsent too, its attach rows pending."""
    store, saved = world.store, b01._ATTEMPTS
    InMemorySubmissionStore(store).seed_account(cr.ref())  # the account's environment (C-2.11)
    world.accounts.append(TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], deleted, KEY))
    b01._ATTEMPTS = OrderedDict()
    rig = order_rig.build_rig(store)
    rig.commands.on_place = order_rig.gated({"ok": True})[1]  # the process goes down first
    try:
        for order in (UNSENT, SENDING):
            await rig.facade.start(order, environment="demo", gates=order_rig.GATES)
        stops = RecordedStopRepository(store.stops)
        await stops.record(_attach_rows(UNSENT), write_ahead=_written)
        if live:
            InMemorySubmissionStore(store).seed_account(cr.ref(cr.LIVE_ACCOUNT, "live"))
            await rig.facade.start(LIVE_UNSENT, environment="live", gates=order_rig.GATES)
            await stops.record(_attach_rows(LIVE_UNSENT, 21), write_ahead=_written)
        await rig.facade.command(cr.ACCOUNT, SENDING.id, "SEND", actor="user")
    finally:
        await rig.facade.stop()
        b01._ATTEMPTS = saved


def recording(monkeypatch: pytest.MonkeyPatch, calls: list[str], target: Any, name: str) -> None:
    """`target.name` records its name in `calls`, then answers as it did."""
    real = getattr(target, name)

    async def recorded(*args: Any, **kwargs: Any) -> Any:
        calls.append(name)
        return await real(*args, **kwargs)

    monkeypatch.setattr(target, name, recorded)


async def test_the_sweep_voids_hydrates_abandons_the_unsent_resumes_the_sent_then_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steps 2 to 5 after a crash, once the flags are read: the account's orphaned attach rows are
    voided and audited before anything hydrates; each unfinished order is hydrated; the one
    recorded and never sent is abandoned (a KILL from `validated`, `startup_unsent`), and the
    create left at the venue's door resumes under its own id, looked up first; `ready` comes
    last."""
    world, calls = World(), list[str]()
    await crashed(world)
    store = world.store
    recording(monkeypatch, calls, store.stops, "void_orphans")
    recording(monkeypatch, calls, store, "list_unfinished")
    recording(monkeypatch, calls, store, "list_for_order")
    async with started(world.runtime()) as runtime:
        killed_when_ready: list[str | None] = []
        ready = runtime._ready.set

        def readied() -> None:
            killed_when_ready.append(store._orders[UNSENT.id].lifecycle_state)
            ready()

        monkeypatch.setattr(runtime._ready, "set", readied)
        waiter = asyncio.create_task(runtime.wait_ready())
        await settle()
        assert (calls, waiter.done(), runtime.state) == ([], False, "starting")  # flags unread
        for flag in world.flags:
            flag.read()
        await until(waiter.done)
        await waiter
        assert runtime.state == "ok" and killed_when_ready == ["killed"]
        assert calls.index("void_orphans") < calls.index("list_unfinished")
        assert calls.index("list_unfinished") < calls.index("list_for_order")
        assert [row.status for row in store._stops.values()] == ["void", "void"]
        swept = [("sl.modified", "unplaced_entry_swept"), ("tp.modified", "unplaced_entry_swept")]
        assert set(swept) <= set(world.writer.actions)
        assert ("orders.cancel", "kill_no_cancel_unsubmitted") in world.writer.actions
        await until(lambda: store._orders[SENDING.id].lifecycle_state != "submitting")
        assert store._orders[SENDING.id].lifecycle_state == "submitted"
        [port] = world.venue.ports
        methods = [call.method for call in port.calls]
        sent = methods.index("place_order")
        assert methods.count("place_order") == 1
        assert sent > 0 and set(methods[:sent]) <= {"open_orders", "order_history"}
        [create] = [call.request for call in port.calls if call.method == "place_order"]
        assert getattr(create, "order_link_id", None) == SENDING.order_link_id


@pytest.mark.parametrize(
    ("intent", "trigger"), [("stop_loss", cr.STOP), ("take_profit", cr.new_order().take_profit)]
)
async def test_native_sl_the_runtimes_kill_cancels_at_the_venue_and_spares_a_recorded_stop(
    intent: str, trigger: Decimal | None
) -> None:
    """E29-T04 S4-B1 wires B1's cancel into the composed runtime: a KILL cancels the sent order at
    the venue once, in the `critical` lane, under its own id (INV-B1-h, C-2.10), accepted, so it
    is audited nothing more; and a recorded stop's row, its stop-loss or its take-profit, is
    spared, its KILL audited and no venue cancel sent for it (C-2.6, INV-B1-p)."""
    world = World()
    await crashed(world)
    stop = cr.new_order(
        seq=7, order_link_id=ext_key("x-sl-0007"), side="Sell", intent=intent,
        order_type="Market", price=None, trigger_price=trigger, stop_loss=None, take_profit=None,
        reduce_only=True, close_on_trigger=True, tpsl_mode="Partial", exchange_order_id="x-sl-0007",
    )  # fmt: skip
    async with started(world.runtime()) as runtime:
        for flag in world.flags:
            flag.read()
        await runtime.wait_ready()
        await until(lambda: world.store._orders[SENDING.id].lifecycle_state == "submitted")
        machines = runtime._composed().machines
        assert await machines.materialise(stop, environment="demo") == "submitted"
        assert await machines.kill("kill switch") == ()
    [port] = world.venue.ports
    cancels = [call for call in port.calls if call.method == "cancel_order"]
    sent = [(call.lane, getattr(call.request, "order_link_id", None)) for call in cancels]
    assert sent == [("critical", SENDING.order_link_id)]
    assert ("orders.cancel", "kill_spared_recorded_stop") in world.writer.actions
    assert [r for _, r in world.writer.actions if str(r).startswith("kill_cancel")] == []


async def test_a_failing_store_leaves_it_not_ready_and_the_sweep_retries_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    InMemorySubmissionStore(world.store).seed_account(cr.ref())
    failures = [StorageQueryFailed("down") for _ in range(2 * SWEEP_MAX_FAILURES)]
    real = world.store.stops.void_orphans

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        if failures:
            raise failures.pop()
        return await real(*args, **kwargs)

    monkeypatch.setattr(world.store.stops, "void_orphans", flaky)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: runtime.state != "starting")
            assert runtime.state == "ok"
    assert world.clock.slept[:4] == [1.0, 2.0, 4.0, 8.0]  # doubled from the first wait
    assert world.clock.slept[-1] == 30.0  # up to the ceiling, retried past `SWEEP_MAX_FAILURES`
    failed = [e["error"] for e in logs if e["event"] == "oms_startup_sweep_failed"]
    assert failed == ["StorageQueryFailed"] * len(world.clock.slept) and not world.pager.calls


async def test_past_max_machines_the_sweep_pages_and_refuses_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 Sec.6.2 step 3: more unfinished orders than the facade holds: paged, nothing hydrated
    or abandoned, and `degraded`, never ready."""
    world, calls = World(), list[str]()
    await crashed(world)
    recording(monkeypatch, calls, world.store, "list_for_order")
    for flag in world.flags:
        flag.read()
    async with started(world.runtime(max_machines=1)) as runtime:
        await until(lambda: runtime.state != "starting")
        assert runtime.state == "degraded" and calls == []
    assert world.store._orders[UNSENT.id].lifecycle_state == "validated"
    assert world.pager.calls == ["oms_startup_overflow: more than 1 unfinished orders"]


async def test_a_resumed_create_on_a_deleted_account_lands_unknown_and_pages() -> None:
    """CR-S3C1B-02, SEC-S3C1C-01: SR-E27-07 deletes an account with orders left unfinished; its
    create, resumed at startup, meets the refusal in the command port: a page, nothing sent, and
    B1 lands it in `unknown` for reconciliation. The unsent one is abandoned all the same (a KILL
    from `validated` reads no account), and the sweep gets ready."""
    world = World()
    await crashed(world, deleted=True)
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await until(lambda: runtime.state != "starting")
        orders = world.store._orders
        await until(lambda: orders[SENDING.id].lifecycle_state != "submitting")
        assert (runtime.state, orders[SENDING.id].lifecycle_state) == ("ok", "unknown")
        assert orders[UNSENT.id].lifecycle_state == "killed"
        assert world.venue.ports[0].calls == []
    assert f"oms_order_account_refused: account {cr.ACCOUNT}" in world.pager.calls


async def test_a_stop_attach_on_a_deleted_account_ends_sl_missing_and_pages() -> None:
    """SEC-S3C1C-01: a partly filled entry whose stop attach was in flight when its process went
    down, its account deleted since with its keys (SR-E27-07): the attach the startup resumes
    meets the refusal, a page, and B1 ends the stop `sl_missing`; the sweep gets ready."""
    world, account = World(), order_rig.ACCOUNT
    ref = AccountRef(account_id=AccountId(account), uid="1", environment="demo", key_ref="k")
    InMemorySubmissionStore(world.store).seed_account(ref)
    world.accounts.append(TradingAccountRow(account, "demo", "1", True, KEY))
    saved, b01._ATTEMPTS = b01._ATTEMPTS, OrderedDict()
    rig = order_rig.build_rig(world.store)
    try:
        order = await rig.submitted()
        rig.commands.on_attach = order_rig.gated(order_rig.READ_BACK)[1]  # in flight at the crash
        await rig.facade.push(account, order.id, "EXEC", order_rig.fill_of(order, "e1", "0.5"))
        await rig.quiet()
        assert rig.facade.state(order.id) == ("partially_filled", "sl_pending")
    finally:
        await rig.facade.stop()
        b01._ATTEMPTS = saved
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        machines = runtime._composed().machines
        await until(lambda: runtime.state != "starting")
        await until(lambda: (machines.state(order.id) or ("", ""))[1] != "sl_pending")
        assert runtime.state == "ok"
        assert machines.state(order.id) == ("partially_filled", "sl_missing")
    assert f"oms_order_account_refused: account {account}" in world.pager.calls


async def test_an_account_refusal_that_reaches_the_sweep_skips_its_order_never_stops_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-S3C1C-01: counted and skipped as a refused history is, never raised out of the sweep:
    the other order is still abandoned and `ready` set."""
    world = World()
    await crashed(world)
    hydrate = OrderMachines.hydrate

    async def refusing(self: OrderMachines, account_id: UUID, order_id: UUID, **kw: Any) -> str:
        if order_id == SENDING.id:
            raise AccountScopeDenied
        return await hydrate(self, account_id, order_id, **kw)

    monkeypatch.setattr(OrderMachines, "hydrate", refusing)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: runtime.state != "starting")
            assert runtime.state == "ok"
            assert world.store._orders[UNSENT.id].lifecycle_state == "killed"
    [skipped] = [e for e in logs if e["event"] == "oms_startup_order_skipped"]
    assert (skipped["order_id"], skipped["reason"]) == (str(SENDING.id), "AccountScopeDenied")
    [swept] = [e for e in logs if e["event"] == "oms_startup_swept"]
    assert (swept["hydrated"], swept["skipped"], swept["abandoned"]) == (1, 1, 1)


@pytest.mark.parametrize(
    ("deleted", "key", "refused"),
    [(True, KEY, AccountScopeDenied), (False, None, OrderEntryRefused), (False, KEY, None)],
)
async def test_the_command_ports_account_read_pages_a_refusal_and_passes_it_on(
    deleted: bool, key: UUID | None, refused: type[Exception] | None
) -> None:
    row = TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], deleted, key)
    binding = TradingAccountsBinding(InMemoryTradingAccountReads(row), environment="demo")
    pager = Pager()
    accounts = CommandAccounts(binding, pager)
    if refused is None:
        assert (await accounts.trading_account(cr.ACCOUNT)).key_ref == str(KEY)
        assert pager.calls == []
    else:
        with pytest.raises(refused):
            await accounts.trading_account(cr.ACCOUNT)
        assert pager.calls == [f"oms_order_account_refused: account {cr.ACCOUNT}"]


async def test_the_sweeps_reads_have_their_own_statement_cap() -> None:
    """CR-S3C1C-01: the order store's 2 s cap would fail every retry on a large history."""
    stores = pg_stores(Settings(), Metrics("demo"))
    try:
        assert isinstance(stores.sweep, SqlAlchemyOrderStore)
        assert isinstance(stores.orders, SqlAlchemyOrderStore)
        assert (stores.sweep._timeout, stores.orders._timeout) == (
            str(SWEEP_STATEMENT_TIMEOUT_MS),
            "2000",
        )
    finally:
        await stores.release()


async def test_the_sweep_leaves_another_environments_stops_pending_and_names_each_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3E3-01, Q20, C-2.11, C-2.6: a live account's entry, recorded and never sent as far as
    this process knows, may still be sending from the live one, so its stops stay `pending`. A demo
    sweep calls `void_orphans` once for each demo account and for no other scope, never for
    `EVERY_ACCOUNT`."""
    world, scopes = World(), list[Any]()
    await crashed(world, live=True)
    InMemorySubmissionStore(world.store).seed_account(cr.ref(DEMO_TWO, "demo"))
    real = world.store.stops.void_orphans

    async def named(scope: Any, **kwargs: Any) -> Any:
        scopes.append(scope)
        return await real(scope, **kwargs)

    monkeypatch.setattr(world.store.stops, "void_orphans", named)
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await until(lambda: runtime.state != "starting")
        assert runtime.state == "ok"
    assert sorted(scopes, key=str) == sorted([cr.ACCOUNT, DEMO_TWO], key=str)
    stops = world.store._stops.values()
    voided = {s.exchange_account_id for s in stops if s.status == "void"}
    pending = {s.exchange_account_id for s in stops if s.status == "pending"}
    assert (voided, pending) == ({cr.ACCOUNT}, {cr.LIVE_ACCOUNT})


async def test_an_error_no_retry_can_outlast_is_met_five_times_then_the_runtime_ends_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3E3-02: an order whose hydration raises an error no refusal names (a `ValueError`) leaves
    the `TaskGroup`'s `ExceptionGroup`, whose causes are logged, not its wrapper alone. It is met
    `SWEEP_MAX_FAILURES` times with the backoff, then given up on and paged: `degraded`, nothing
    abandoned (step 4 never ran), no order skipped on an error no refusal names."""
    world = World()
    await crashed(world)

    async def broken(self: OrderMachines, account_id: UUID, order_id: UUID, **kw: Any) -> str:
        raise ValueError("an order the facade cannot read")

    monkeypatch.setattr(OrderMachines, "hydrate", broken)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: runtime.state == "degraded")
    failed = [(e["error"], e["causes"]) for e in logs if e["event"] == "oms_startup_sweep_failed"]
    assert failed == [("ExceptionGroup", ["ValueError"])] * SWEEP_MAX_FAILURES
    assert world.clock.slept == [1.0, 2.0, 4.0, 8.0]  # no wait after the last attempt
    assert world.pager.calls == ["oms_startup_sweep_gave_up: ValueError"]
    assert world.store._orders[UNSENT.id].lifecycle_state == "validated"


async def test_a_stop_that_meets_a_failing_hydration_ends_the_startup_never_retries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop's cancel that meets a hydration failing (here, as it is cancelled) leaves the
    `TaskGroup` as an `ExceptionGroup`, not a `CancelledError`: the startup task ends there,
    cancelled and logged, with no retry over the parts the stop closes. A startup task the stop
    did not end (the regression) is let go once the runtime has stopped, so the test fails on it
    instead of hanging in its teardown."""
    world, flying, release = World(), asyncio.Event(), asyncio.Event()
    await crashed(world)

    async def failing(self: OrderMachines, account_id: UUID, order_id: UUID, **kw: Any) -> str:
        flying.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            raise StorageQueryFailed("the connection went with the stop") from None
        return "submitted"

    monkeypatch.setattr(OrderMachines, "hydrate", failing)
    for flag in world.flags:
        flag.read()
    try:
        with capture_logs() as logs:
            async with started(world.runtime()) as runtime:
                startup = runtime._startup
                await until(flying.is_set)
    finally:
        release.set()  # a regression's retried hydrations return, so nothing hangs
    assert startup is not None and startup.cancelled() and world.clock.slept == []
    events = [e["event"] for e in logs if e["event"].startswith("oms_startup_s")]
    assert events == ["oms_startup_stopped"]


@pytest.mark.parametrize("read", ["environment_accounts", "void_orphans", "list_unfinished"])
async def test_a_sweep_read_that_stalls_times_out_is_logged_and_retried(
    read: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-S3E3-03: each of the sweep's store calls has its statement cap plus a slack as its own
    client-side bound, so a stalled connection is a logged, retried `TimeoutError`, not an OMS left
    `starting` with no line in the log."""
    monkeypatch.setattr(oms_wiring, "SWEEP_STATEMENT_TIMEOUT_MS", 0)
    monkeypatch.setattr(oms_wiring, "SWEEP_CALL_SLACK_S", 0.3)  # real time, kept short
    world, stalled = World(), list[bool]()
    InMemorySubmissionStore(world.store).seed_account(cr.ref())
    target = world.store.stops if read == "void_orphans" else world.store
    real = getattr(target, read)

    async def stalls_once(*args: Any, **kwargs: Any) -> Any:
        if not stalled:
            stalled.append(True)
            await asyncio.Event().wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(target, read, stalls_once)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            async with asyncio.timeout(10):  # a bound on the test
                await runtime.wait_ready()
    failed = [e["error"] for e in logs if e["event"] == "oms_startup_sweep_failed"]
    assert failed == ["TimeoutError"] and world.clock.slept == [1.0]


async def test_a_history_the_facade_refuses_is_paged_skipped_and_the_sweep_still_gets_ready() -> (
    None
):
    """CR-S3E3-04, 20 Sec.6.2 step 3: an order whose events do not rebuild its row (OM-T03) is
    paged by the facade, counted and skipped (`OrderHistoryRefused` is in `_SKIPPED`); the unsent
    one is abandoned and `ready` is set."""
    world = World()
    await crashed(world)
    row = world.store._orders[SENDING.id]
    world.store._orders[SENDING.id] = replace(row, qty=row.qty + 1)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: runtime.state != "starting")
            assert runtime.state == "ok"
    [skipped] = [e for e in logs if e["event"] == "oms_startup_order_skipped"]
    assert (skipped["order_id"], skipped["reason"]) == (str(SENDING.id), "OrderHistoryRefused")
    [swept] = [e for e in logs if e["event"] == "oms_startup_swept"]
    assert (swept["hydrated"], swept["skipped"], swept["abandoned"]) == (1, 1, 1)
    assert world.pager.calls == ["oms_order_history_refused"]


async def test_the_sweep_hydrates_at_most_eight_orders_at_once_and_logs_how_long_it_took(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3E3-04, CR-S3E3-05: a gate in `hydrate` shows `HYDRATE_CONCURRENCY` orders in flight
    though more are due, and `oms_startup_swept` carries the sweep's time on the injected clock."""
    world, held, flying, peak = World(), asyncio.Event(), 0, 0
    rows = [
        SimpleNamespace(id=UUID(int=n), exchange_account_id=cr.ACCOUNT)
        for n in range(HYDRATE_CONCURRENCY + 4)
    ]

    async def listed(environment: str, *, limit: int) -> Any:
        return tuple(rows)

    async def gated(self: OrderMachines, account_id: UUID, order_id: UUID, **kw: Any) -> str:
        nonlocal flying, peak
        flying += 1
        peak = max(peak, flying)
        await held.wait()
        flying -= 1
        return "submitted"

    monkeypatch.setattr(world.store, "list_unfinished", listed)
    monkeypatch.setattr(OrderMachines, "hydrate", gated)
    for flag in world.flags:
        flag.read()
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: flying >= HYDRATE_CONCURRENCY)
            await settle()  # a ninth would have started by now
            assert peak == HYDRATE_CONCURRENCY
            world.clock.s += 2.5  # the sweep takes this long
            held.set()
            await until(lambda: runtime.state == "ok")
    [swept] = [e for e in logs if e["event"] == "oms_startup_swept"]
    assert (swept["hydrated"], swept["elapsed_s"], peak) == (len(rows), 2.5, HYDRATE_CONCURRENCY)


async def test_a_sweep_that_ends_while_the_stop_drains_does_not_set_ready_again() -> None:
    """CR-S3E3-06: `stop()` clears `ready`, then drains the submits for up to `CV_OMS_DRAIN_S`
    while the startup task runs on; a sweep that ends meanwhile must not set it."""
    world = World()
    async with started(world.runtime()) as runtime:
        startup, submit = runtime._startup, runtime.run(asyncio.Event().wait())
        assert startup is not None
        stopping = asyncio.create_task(runtime.stop())
        await settle()  # the stop is draining the submit
        for flag in world.flags:
            flag.read()
        await until(startup.done)
        assert not runtime._ready.is_set()
        submit.cancel()
        await stopping


async def test_a_refused_reference_price_holds_a_ticker_demand_until_the_stop() -> None:
    """CR-S3B2-03, composed: the pipeline's price binding asks the runtime's ticker demand, which
    the stop lets go."""
    world, demands = World(), list[tuple[str, str]]()
    world.ingestion.tickers = SimpleNamespace(
        latest=lambda _symbol: None,
        is_stale=lambda _symbol: False,
        acquire=lambda _consumer, symbol: demands.append(("acquire", symbol)),
        release=lambda _consumer, symbol: demands.append(("release", symbol)),
    )
    async with started(world.runtime()) as runtime:
        assert await runtime._composed().submission._deps.prices.reference_price("SOLUSDT") is None
    assert demands == [("acquire", "SOLUSDT"), ("release", "SOLUSDT")]


class Stalled(Port):
    """A venue whose positions read never answers; it notes the read and its cancellation."""

    asked = cancelled = False

    async def positions(self, account: AccountRef) -> list[Position]:
        self.asked = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


@dataclass
class StalledVenue(Venue):
    def trading_port(self, env: str, *, clock_offset_ms: Any = None) -> Port:
        self.ports.append(Stalled(environment=cast(Environment, env)))
        return self.ports[-1]


async def waiting_stop(world: World, *, deleted: bool = False) -> None:
    """The demo account's trading-stop request, left unanswered by a process that went down."""
    InMemorySubmissionStore(world.store).seed_account(cr.ref())
    world.accounts.append(TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], deleted, KEY))
    row = NewRecordedStop(
        id=UUID(int=31), exchange_account_id=cr.ACCOUNT, symbol=cr.SYMBOL, position_idx=0,
        position_side="Buy", kind="stop_loss", source="trading_stop", order_id=None,
        tpsl_mode="Full", trigger_price=cr.STOP, size=None, audit_record_id=UUID(int=32),
        actor_user_id=None,
    )  # fmt: skip
    await RecordedStopRepository(world.store.stops).record([row], write_ahead=_written)
    for flag in world.flags:
        flag.read()


async def test_the_startup_pass_never_holds_ready_and_stop_cancels_its_read() -> None:
    """20 Sec.6.2 step 2: the complete read of a waiting key starts after `void_orphans` and nothing
    waits for it, so a venue that never answers leaves `ready` set; `stop()` cancels the read."""
    world = World(venue=StalledVenue())
    await waiting_stop(world)
    async with started(world.runtime()) as runtime:
        [port] = world.venue.ports
        assert isinstance(port, Stalled)
        await until(lambda: port.asked and runtime.state != "starting")
        assert runtime.state == "ok"
        closers = [name for name, _ in runtime._composed().closers]
        # the exit service's tasks end first (slice 4), then the gate's reads (CR-S3H3B-01)
        assert closers[:3] == ["exits", "stop_gate", "machines"]
    assert port.cancelled
    assert [row.status for row in world.store._stops.values()] == ["pending"]


async def test_a_refused_accounts_waiting_keys_are_paged_and_never_read() -> None:
    """20 Sec.6.2 step 2: an account the binding refuses (soft-deleted) is paged, and its keys stay
    refused, never read, while the runtime gets ready."""
    world = World()
    await waiting_stop(world, deleted=True)
    async with started(world.runtime()) as runtime:
        await until(lambda: runtime.state != "starting" and bool(world.pager.calls))
        assert runtime.state == "ok" and world.venue.ports[0].calls == []
    assert world.pager.calls == [f"oms_order_account_refused: account {cr.ACCOUNT}"]
    assert [row.status for row in world.store._stops.values()] == ["pending"]


async def test_a_floor_read_that_fails_is_retried_and_the_gate_refuses_until_it_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3H3B-02 (20 Sec.6.2, Q7): the database's clock failing once fails the sweep, which
    retries after its backoff; meanwhile the gate judges nothing (`StoreUnavailable`), and once
    the start is read the runtime gets ready and the gate answers."""
    world, release, backoffs = World(), asyncio.Event(), list[float]()
    database_now, failures = world.store.stops.database_now, [StorageQueryFailed("down")]

    async def flaky() -> datetime:
        if failures:
            raise failures.pop()
        return await database_now()

    async def backoff(seconds: float) -> None:
        backoffs.append(seconds)
        await release.wait()

    monkeypatch.setattr(world.store.stops, "database_now", flaky)
    for flag in world.flags:
        flag.read()
    key = PositionKey(cr.ACCOUNT, cr.SYMBOL, 0)
    async with started(world.runtime(sleep=backoff)) as runtime:
        await until(lambda: bool(backoffs))
        with pytest.raises(StoreUnavailable):
            await runtime._composed().gate.clear(key)
        release.set()
        await until(lambda: runtime.state == "ok")
        await runtime._composed().gate.clear(key)  # read: nothing waits for the key
    assert backoffs == [1.0]
