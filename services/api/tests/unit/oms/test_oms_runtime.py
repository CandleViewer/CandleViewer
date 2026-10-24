"""#913 slice 3E (E29-T04): the OMS runtime (`oms_wiring.OmsRuntime`, 20 Sec.6.2) on fakes. Its
composition for the process's environment, the sink it takes, builds or refuses (rulings Q4 to Q6),
the interim announcements, closing what a failed composition built, and one facade per process;
its lifecycle: the startup's waits, `run`, the stop's drain, and the state `/readyz` gives. No I/O:
in-memory stores, a fake venue, and a clock that moves only when the runtime sleeps on it."""

from __future__ import annotations

import asyncio
import inspect
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer import oms_wiring
from candleviewer.api.health import make_health_router
from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import RateLane
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.fakes import FakeClockHealth, InMemoryOrderStore
from candleviewer.oms_wiring import OmsRuntime, OmsStores, build_oms_runtime
from candleviewer.settings import Environment as Env
from candleviewer.settings import Settings
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import ChainTripLatch, DegradedLatchError, MachineKey
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.repositories.trade_groups import TradeGroupStore
from candleviewer.storage.repositories.trading_accounts import InMemoryTradingAccountReads
from tests._signing import fake_capability
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
            anchors=store.anchors, stops=store.stops, groups=cast(TradeGroupStore, None),
            accounts=InMemoryTradingAccountReads(*self.accounts),
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
    monkeypatch.setattr(oms_wiring, "OMS_STOP_RESERVE_S", 1.5)  # the hung sink costs a third of it

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
