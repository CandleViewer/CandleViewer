"""#913 slice 3E (E29-T04): the OMS runtime (`oms_wiring.OmsRuntime`, 20 Sec.6.2) on fakes. Its
composition for the process's environment, the sink it takes, builds or refuses (rulings Q4 to Q6),
the interim announcements, closing what a failed composition built, and one facade per process.
No I/O: in-memory stores, a fake venue, and a clock that moves only when the runtime sleeps on
it."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import RateLane
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.fakes import FakeClockHealth, InMemoryOrderStore
from candleviewer.oms_wiring import OmsRuntime, OmsStores
from candleviewer.settings import Environment as Env
from candleviewer.settings import Settings
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.persistence import ChainTripLatch, DegradedLatchError, MachineKey
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.repositories.trade_groups import TradeGroupStore
from candleviewer.storage.repositories.trading_accounts import InMemoryTradingAccountReads
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
            "monotonic": self.clock, "registry": REGISTRY,
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
