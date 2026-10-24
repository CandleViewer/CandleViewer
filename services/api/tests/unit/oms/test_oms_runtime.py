"""#913 slice 3E (E29-T04): the OMS runtime (`oms_wiring.OmsRuntime`, 20 Sec.6.2) on fakes. Its
composition for the process's environment, the sink it takes, builds or refuses (rulings Q4 to Q6),
the interim announcements, closing what a failed composition built, and one facade per process;
its lifecycle: the startup's waits, `run`, the stop's drain, and the state `/readyz` gives; and
the startup sweep after a crash. No I/O: in-memory stores, a fake venue, and a clock that moves only
when the runtime sleeps on it."""

from __future__ import annotations

import asyncio
import inspect
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
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
from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, Position, RateLane
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsNotReady,
    OrderEntryRefused,
    StoreUnavailable,
)
from candleviewer.oms.fakes import FakeClockHealth, InMemoryOrderStore, InMemorySubmissionStore
from candleviewer.oms.order_machine import OrderMachines
from candleviewer.oms.ports import PositionKey
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.oms_wiring import (
    HYDRATE_CONCURRENCY,
    SWEEP_MAX_FAILURES,
    SWEEP_STATEMENT_TIMEOUT_MS,
    CommandAccounts,
    GroupStores,
    OmsRuntime,
    OmsStores,
    TradingAccountsBinding,
    build_oms_runtime,
    pg_stores,
)
from candleviewer.settings import Environment as Env
from candleviewer.settings import Settings
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import ChainTripLatch, DegradedLatchError, MachineKey
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import NewOrder
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, RecordedStopRow
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
INTERIMS = ("sizer", "stop_resolver", "risk_gate", "arm_records", "kill_switch")


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
    """The standalone sink the stores build; its start and stop land in the world's log."""

    def __init__(self, log: list[str], fail: Exception | None = None) -> None:
        super().__init__()
        self.log, self.fail = log, fail

    async def start(self) -> None:
        self.log.append("sink.start")
        if self.fail is not None:
            raise self.fail

    async def stop(self) -> None:
        self.log.append("sink.stop")


@dataclass
class Writer:
    """The audit writer: each append, by its action and reason."""

    actions: list[tuple[str, str | None]] = field(default_factory=list)

    async def emit(self, action: str, **fields: Any) -> None:
        self.actions.append((action, fields.get("reason")))

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None:
        self.actions.append((action, fields.get("reason")))


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

    def __post_init__(self) -> None:
        self.health = FakeClockHealth(self.clock)
        self.health.measure()
        self.ingestion = SimpleNamespace(
            clock=self.health, tickers=None, instruments=None, clock_offset_ms=lambda: None
        )

    def stores(self) -> OmsStores:
        store = self.store

        async def release() -> None:
            self.log.append("pool.release")

        return OmsStores(
            orders=store, executions=store.executions, submissions=store.submissions,
            anchors=store.anchors, stops=store.stops, groups=cast(GroupStores, None),
            accounts=InMemoryTradingAccountReads(*self.accounts), sweep=store,
            sink=lambda: Sink(self.log, self.sink_fails), release=release,
        )  # fmt: skip

    def runtime(
        self, environment: str = "demo", *, live_on: bool = False, bundle: Any = None, **over: Any
    ) -> OmsRuntime:
        settings = Settings(environment=Env(environment), trading_live_enabled=live_on)
        feed = SimpleNamespace(bind=lambda _b: SimpleNamespace(publish=lambda *_a, **_k: None))
        built: dict[str, Any] = {
            "venue": self.venue, "ingestion": self.ingestion, "read_only": ReadOnly(),
            "metrics": self.metrics, "audit": self.writer,
            "gate": SimpleNamespace(refusal=lambda _account: None), "standings": self.standings,
            "live_enabled": self.flags[1], "profiles": Profiles(), "persistence": bundle,
            "feed": feed, "stores": self.stores, "pager": self.pager, "now": lambda: T0,
            "monotonic": self.clock, "registry": REGISTRY, "oms_enabled": self.flags[0],
            "sleep": self.clock.sleep,
        }  # fmt: skip
        return OmsRuntime(settings, **(built | over))

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
            assert runtime.submission._anchors is runtime.anchors  # SEC-S3D-02: the one service
            assert world.log == ["sink.start"]
    warned = [e["port"] for e in logs if e["event"] == "oms_interim_port"]
    assert warned == [*INTERIMS, "machine_event_sink"]  # one WARNING each
    assert [world.gauge(name) for name in (*INTERIMS, "machine_event_sink")] == [1.0] * 6
    assert world.log == ["sink.start", "sink.stop", "pool.release"] and port.closed
    assert not b01.ports_wired()


@pytest.mark.parametrize(
    ("environment", "live_on", "with_bundle", "sink"),
    [
        ("demo", True, False, "standalone"),
        ("testnet", True, False, "standalone"),
        ("live", False, False, "standalone"),
        ("live", True, True, "bundle"),
        ("live", True, False, None),
    ],
)
async def test_the_sink_is_the_bundles_else_a_standalone_one_never_on_live_with_the_setting_on(
    environment: str, live_on: bool, with_bundle: bool, sink: str | None
) -> None:
    """Rulings Q4 to Q6 (20 Sec.6.2): the bundle's sink and latch when there is one; else the WAL
    sink it builds and owns, in demo and testnet whatever the setting says and in live while it is
    off; a live process with it on and no bundle fails closed: no sink, no order served."""
    world = World()
    bundle = SimpleNamespace(sink=InMemoryMachineEventSink(), latch=ChainTripLatch())
    runtime = world.runtime(environment, live_on=live_on, bundle=bundle if with_bundle else None)
    with capture_logs() as logs:
        async with started(runtime):
            if sink is None:
                assert failed_closed(logs) == ["NoMachineEventSink"] and not b01.ports_wired()
                assert world.pager.calls == ["oms_runtime_failed_closed: sink"]  # CR-S3E1-02
                assert failed_phases(logs) == ["sink"]
                assert world.venue.ports == [] and world.log == []
                with pytest.raises(OmsNotReady):
                    _ = runtime.submission
            else:
                assert world.log == (["sink.start"] if sink == "standalone" else [])
                assert failed_closed(logs) == [] and b01.ports_wired()
    assert world.gauge("machine_event_sink") == (0.0 if with_bundle else 1.0)


async def test_a_composition_that_fails_late_closes_what_it_built_and_fails_closed() -> None:
    """The sink's start refuses (another process holds its WAL): the facade is unwired again and
    the port and the pool closed; the runtime serves no order."""
    world = World(sink_fails=RuntimeError("the WAL is locked"))
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            assert failed_closed(logs) == ["RuntimeError"] and not b01.ports_wired()
            assert world.log == ["sink.start", "pool.release"] and world.venue.ports[0].closed
            assert world.pager.calls == ["oms_runtime_failed_closed: sink_start"]
            assert failed_phases(logs) == ["sink_start"]
            assert world.pager.severities == ["page"]
            with pytest.raises(OmsNotReady):
                _ = runtime.anchors


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
            assert port.closed and world.log == []


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
            with pytest.raises(OmsNotReady):
                _ = runtime.submission


def test_the_fake_backend_composes_no_oms_runtime() -> None:
    """20 Sec.6.2: no runtime, so `placeOrder` answers `501 not_implemented` there."""
    names = ("metrics", "audit", "gate", "standings", "oms_enabled", "live_enabled")
    unused = dict.fromkeys((*names, "profiles", "persistence", "feed"))
    assert build_oms_runtime(cast(Any, None), Settings(), **cast(Any, unused)) is None


async def test_the_state_is_starting_while_the_startup_runs_and_degraded_once_failed_closed() -> (
    None
):
    world = World()
    async with started(world.runtime()) as runtime:
        assert (runtime.started, runtime.state) == (True, "starting")  # waiting on the flags
    assert not runtime.started
    async with started(world.runtime("live", live_on=True)) as runtime:
        assert (runtime.started, runtime.state) == (True, "degraded")  # no bundle: never ready


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
    # the hung sink, 4th of the 6 closers (the stop gate's first, CR-S3H3B-01), costs a third of it
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
    assert world.venue.ports[0].closed and world.log == ["sink.start", "pool.release"]
    assert not b01.ports_wired()  # the facade, first in line, closed too


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
        assert await runtime.submission._deps.prices.reference_price("SOLUSDT") is None
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
        assert closers[:2] == ["stop_gate", "machines"]  # its reads end first (CR-S3H3B-01)
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
