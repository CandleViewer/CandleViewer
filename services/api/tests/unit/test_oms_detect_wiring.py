"""E29-T08's composition (#916; 24-internal-schemas.md Sec.8.13; 20-architecture.md Sec.6.2,
Sec.7.2, Sec.12.1): the sinks' adapters, `bybit_rate_remaining` over the trading port's headroom
(BQ-11), the detector's own pool, its closer and its `/readyz` stall, and `CV_OMS_PENDING_STUCK_S`.
No network:
the bus is the real in-process one, the stores and the port are doubles, and the runtime runs on
`test_oms_runtime`'s world."""

from __future__ import annotations

import asyncio
import functools
import math
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import pytest
from prometheus_client import generate_latest
from pydantic import ValidationError

from candleviewer import oms_detect_wiring
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.fakes import FRESH_HEADROOM_TOKENS
from candleviewer.exchange.base.models import AccountRef, RateHeadroom
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OrderRefused
from candleviewer.oms.incidents import DETAILS, OmsIncident, incident
from candleviewer.oms.stuck_detector import StuckDetector
from candleviewer.oms_detect_wiring import (
    DETECT_POOL_NAME,
    DETECT_POOL_SIZE,
    MAX_PUBLISHING,
    RATE_LANES,
    BusIncidents,
    DetectRuntime,
    DetectStores,
    IncidentAuditRecords,
    IncidentEventRows,
    RateRemaining,
    ServedIncidentBus,
    stop_detection,
    thresholds_of,
)
from candleviewer.oms_wiring import build_detect_stores
from candleviewer.settings import Settings
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT
from candleviewer.storage.repositories.stuck import InMemoryStuckReads
from candleviewer.storage.repositories.stuck_sqlalchemy import SqlAlchemyStuckReads
from tests.unit.oms.order_rig import Pager
from tests.unit.oms.stuck_rig import ACCOUNT, OTHER, T0, link

#: The incidents these tests hand the sinks.
STUCK = incident("in_flight", account_id=ACCOUNT, age_s=31.5, detected_at=T0,
                 order_link_id=link(1), symbol="BTCUSDT")  # fmt: skip
NAKED = incident("naked", account_id=OTHER, age_s=3.5, detected_at=T0, symbol="ETHUSDT")
#: An active key's id in its canonical form, as the trading port requires (ruling R13).
KEY_REF = str(UUID(int=7))


def test_the_thresholds_are_the_settings_and_one_cycle() -> None:
    t = thresholds_of(Settings())
    assert (t.in_flight_s, t.unknown_s, t.pending_s, t.naked_s) == (30.0, 30.0, 15.0, 3.0)
    changed = thresholds_of(Settings(oms_pending_stuck_s=20, native_sl_deadline_ms=2500))
    assert (changed.pending_s, changed.naked_s) == (20.0, 2.5)


@pytest.mark.parametrize("value", ["15", "10.001", "120"])
def test_the_pending_threshold_lies_above_b1s_command_timeout_and_at_most_120(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_OMS_PENDING_STUCK_S", value)
    assert Settings().oms_pending_stuck_s == float(value)


@pytest.mark.parametrize("value", ["10", "9", "120.5", "nan", "inf"])
def test_a_pending_threshold_off_its_bounds_refuses_startup(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_OMS_PENDING_STUCK_S", value)
    with pytest.raises(ValidationError, match="oms_pending_stuck_s"):
        Settings()


def test_the_floor_is_b1s_command_timeout() -> None:
    """M1 may not import `oms`, so settings spells B1's 10 s out; the two are pinned alike."""
    floor = next(
        rule.gt for rule in Settings.model_fields["oms_pending_stuck_s"].metadata
        if hasattr(rule, "gt")
    )  # fmt: skip
    assert floor == CV_COMMAND_TIMEOUT == 10.0


# --- The sinks' adapters ------------------------------------------------------------------------


@dataclass
class Emitter:
    emitted: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def emit(self, action: str, **fields: Any) -> None:
        self.emitted.append((action, fields))


async def test_the_record_is_oms_incident_as_the_system_its_state_the_incident() -> None:
    emitter = Emitter()
    await IncidentAuditRecords(emitter, environment="demo").write(
        STUCK, object_kind="order", object_id=str(UUID(int=1))
    )
    [(action, fields)] = emitter.emitted
    assert action == "oms.incident"
    assert {k: fields[k] for k in ("actor_label", "actor_user_id", "object_kind", "object_id",
                                   "outcome", "severity", "reason", "request_id", "env")} == {
        "actor_label": "system:oms", "actor_user_id": None, "object_kind": "order",
        "object_id": str(UUID(int=1)), "outcome": "success", "severity": "error",
        "reason": "in_flight", "request_id": None, "env": "demo",
    }  # fmt: skip
    assert fields["after_state"]["order_link_id"] == link(1)
    assert fields["after_state"]["age_s"] == "31.500"


@dataclass
class EventWriter:
    rows: list[SystemEvent] = field(default_factory=list)

    async def write(self, event: SystemEvent) -> None:
        self.rows.append(event)


async def test_the_row_is_an_oms_incident_kind_its_fixed_sentence_and_ids() -> None:
    writer = EventWriter()
    await IncidentEventRows(writer).write(NAKED)
    [row] = writer.rows
    assert (row.component, row.kind, row.severity, row.message) == (
        "oms", "incident_naked", "critical", DETAILS["naked"]
    )  # fmt: skip
    assert row.details == {
        "kind": "naked", "account_id": str(OTHER), "age_s": "3.500", "symbol": "ETHUSDT"
    }  # fmt: skip


async def test_the_bus_carries_the_frozen_incident_on_env_oms_incident() -> None:
    bus = Bus()
    sub = bus.subscribe("t", "demo.oms.incident", QueuePolicy.NEVER_DROP)
    publisher = BusIncidents(bus, environment="demo")
    assert publisher.topic.key == "demo.oms.incident"
    publisher.offer(STUCK)
    got = await asyncio.wait_for(sub.get(), 2.0)
    assert got is STUCK and isinstance(got, OmsIncident)
    await publisher.aclose()


async def test_the_bus_holds_at_most_its_cap_in_flight_and_its_close_cancels_them() -> None:
    bus = Bus()
    bus.subscribe("full", "demo.oms.incident", QueuePolicy.NEVER_DROP, maxsize=1)
    publisher = BusIncidents(bus, environment="demo")
    for _ in range(MAX_PUBLISHING + 5):  # the first fills the queue, the rest wait on it
        publisher.offer(STUCK)
    await asyncio.sleep(0)
    assert len(publisher._tasks) == MAX_PUBLISHING
    await publisher.aclose()
    assert publisher._tasks == set()


async def test_the_lane_hands_each_incident_to_the_serving_loop_never_awaited() -> None:
    notified: list[tuple[Any, tuple[Any, ...]]] = []

    class Serving:
        def notify(self, fn: Any, /, *args: Any, **_k: Any) -> None:
            notified.append((fn, args))

    publisher = BusIncidents(Bus(), environment="demo")
    ServedIncidentBus(publisher, Serving()).offer(STUCK)
    assert notified == [(publisher.offer, (STUCK,))]


# --- bybit_rate_remaining (BQ-11) ---------------------------------------------------------------


@dataclass
class Port:
    tokens: dict[str, float] = field(default_factory=dict)
    fail: bool = False

    def headroom(self, account: AccountRef, lane: Any) -> RateHeadroom:
        if self.fail:
            raise ValueError("another environment's account")
        return RateHeadroom(lane=lane, tokens=self.tokens[account.uid], wait_s=0.0)


def _ref(account: UUID, uid: str) -> AccountRef:
    return AccountRef(account_id=AccountId(account), uid=uid, environment="demo", key_ref="k")


def _rate(port: Port, refs: dict[UUID, AccountRef | Exception]) -> tuple[RateRemaining, Metrics]:
    clock = [0.0]
    metrics = Metrics("demo")

    async def accounts(_env: str) -> tuple[UUID, ...]:
        return tuple(refs)

    async def resolve(account_id: AccountId) -> AccountRef:
        got = refs[account_id]
        if isinstance(got, Exception):
            raise got
        return got

    rate = RateRemaining(
        metrics, port, environment="demo", account_ids=accounts, resolve=resolve,
        monotonic=lambda: clock[0],
    )  # fmt: skip
    return rate, metrics


def _scraped(metrics: Metrics, lane: str) -> float:
    for line in generate_latest(metrics.registry).decode().splitlines():
        if line.startswith(f'bybit_rate_remaining{{endpoint_group="{lane}",env="demo"}}'):
            return float(line.rsplit(" ", 1)[1])
        if line.startswith(f'bybit_rate_remaining{{env="demo",endpoint_group="{lane}"}}'):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"no {lane} child")


async def test_the_rate_gauge_is_the_fewest_tokens_across_the_accounts_per_lane() -> None:
    port = Port({"u1": 7.0, "u2": 3.5})
    refused = OrderRefused("no_active_key")
    rate, metrics = _rate(port, {ACCOUNT: _ref(ACCOUNT, "u1"), OTHER: _ref(OTHER, "u2"),
                                 UUID(int=9): refused})  # fmt: skip
    assert all(math.isnan(_scraped(metrics, lane)) for lane in RATE_LANES)  # none read yet
    await rate.refresh()
    assert [_scraped(metrics, lane) for lane in RATE_LANES] == [3.5] * len(RATE_LANES)
    port.fail = True
    assert math.isnan(rate.remaining("entry"))  # a port that cannot read never breaks a scrape


async def test_the_accounts_are_read_again_at_most_every_30_s() -> None:
    port = Port({"u1": 7.0})
    refs: dict[UUID, AccountRef | Exception] = {ACCOUNT: _ref(ACCOUNT, "u1")}
    rate, _metrics = _rate(port, refs)
    await rate.refresh()
    refs.clear()
    await rate.refresh()  # inside 30 s: not read again
    assert rate.remaining("poll") == 7.0


def test_the_gauge_names_the_closed_lane_set_and_no_account() -> None:
    assert sorted(RATE_LANES) == ["critical", "entry", "poll"]


# --- Its stores, its handle and its stop ---------------------------------------------------------


def test_its_stores_are_on_a_pool_of_their_own_at_the_stores_cap() -> None:
    """The runtime's module builds them, as it alone names the principal-free account reads the
    rate gauge resolves its accounts through (C-12.4)."""
    stores = build_detect_stores(Settings(oms_statement_timeout_ms=1800))
    assert isinstance(stores.reads, SqlAlchemyStuckReads)
    pool = stores.reads._relational
    assert pool._application_name_suffix == DETECT_POOL_NAME == "oms-detect"
    queue: Any = pool.engine.pool  # the async engine's queue pool, sized as built
    assert (queue.size(), queue._max_overflow) == (DETECT_POOL_SIZE, 0)
    assert stores.reads._timeout == "1800"
    events: Any = stores.events  # `PgSystemEventWriter`, typed as the port
    assert events._repo is pool  # its rows on the same pool, never the OMS's


async def _unread(_account_id: AccountId) -> AccountRef:
    raise OrderRefused("no account resolves in this test")


@dataclass
class Released:
    calls: list[str] = field(default_factory=list)

    async def release(self) -> None:
        self.calls.append("release")


class Loop:
    """The scan loop's double: it runs until `gate` is set, then ends on an error."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()

    async def run(self) -> None:
        await self.gate.wait()
        raise RuntimeError("the loop ended")

    def stalled(self) -> bool:
        return False


def _runtime(released: Released, pager: Pager, loop: Loop | None = None) -> DetectRuntime:
    async def accounts(_env: str) -> tuple[UUID, ...]:
        return ()

    stores = DetectStores(
        reads=InMemoryStuckReads(), events=EventWriter(), account_ids=accounts, resolve=_unread,
        release=released.release,
    )  # fmt: skip
    publisher = BusIncidents(Bus(), environment="demo")
    return DetectRuntime(loop or Loop(), stores, publisher, pager)


async def test_its_close_cancels_the_scan_then_releases_its_pool() -> None:
    released, pager = Released(), Pager()
    detect = _runtime(released, pager)
    detect.start()
    await asyncio.sleep(0)
    await detect.aclose()
    assert released.calls == ["release"]
    assert pager.calls == []  # a cancelled loop pages nothing


async def test_a_loop_that_ends_on_its_own_is_logged_critical_and_paged() -> None:
    released, pager, loop = Released(), Pager(), Loop()
    detect = _runtime(released, pager, loop)
    detect.start()
    loop.gate.set()
    for _ in range(4):
        await asyncio.sleep(0)
    assert pager.calls == ["oms_detector_ended"]
    await detect.aclose()


async def test_the_stop_runs_the_lanes_half_then_the_serving_loops() -> None:
    order: list[str] = []

    class Lane:
        def call(self, coro: Any, *, timeout_s: float | None = None) -> Any:
            order.append("lane")
            return coro

    class Serving:
        async def call(self, coro: Any, *, timeout_s: float = 10.0) -> Any:
            order.append("serving")
            return await coro

    detect = _runtime(Released(), Pager())
    await stop_detection(Lane(), Serving(), detect)
    assert order == ["lane", "serving"]


# --- In the runtime -----------------------------------------------------------------------------


def _with_detection(world: Any, stores: DetectStores, bus: Bus | None = None) -> Any:
    held = Bus() if bus is None else bus
    return world.runtime(stores=lambda: replace(world.stores(), detect=stores), bus=held)


async def test_the_runtime_composes_it_closes_it_first_and_degrades_on_its_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.oms.test_handovers import _Store
    from tests.unit.oms.test_oms_runtime import World, started
    from tests.unit.test_oms_reconcile_wiring import Reads

    released = Released()

    async def accounts(_env: str) -> tuple[UUID, ...]:
        return ()

    stores = DetectStores(
        reads=InMemoryStuckReads(), events=EventWriter(), account_ids=accounts, resolve=_unread,
        release=released.release,
    )  # fmt: skip
    world = World(handover_store=_Store(), reconcile_reads=Reads())
    for flag in world.flags:
        flag.read()
    async with started(_with_detection(world, stores)) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
        parts = runtime._composed()
        assert parts.detect is not None
        names = [name for name, _ in parts.closers]
        assert names.index("stuck_detector") + 1 == names.index("reconciliation")
        assert all(
            names.index("stuck_detector") < names.index(used)
            for used in ("stop_gate", "machines", "audit", "pool", "environment_lock")
        )
        monkeypatch.setattr(parts.detect, "stalled", lambda: True)
        assert runtime.readyz == "degraded" and runtime.readiness == "ok"  # entry never waits
    assert released.calls == ["release"]


class Parked:
    """The detector's sleep in the runtime, on logical time: each wait is noted, then parks until
    the test lets one through, so the loop scans only as far as the test moves it."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self._through = asyncio.Semaphore(0)
        self._noted = asyncio.Condition()

    async def sleep(self, seconds: float) -> None:
        async with self._noted:
            self.waits.append(seconds)
            self._noted.notify_all()
        await self._through.acquire()

    def through(self, waits: int) -> None:
        for _ in range(waits):
            self._through.release()

    async def parked(self, waits: int) -> None:
        async with self._noted:
            await self._noted.wait_for(lambda: len(self.waits) >= waits)


async def test_the_runtime_scans_its_own_standing_and_refreshes_the_rate_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As composed (BQ-2, BQ-11): an account the runtime's own standing marks stale is raised at
    the next scan, recorded ahead and offered to the bus, and the scan's chore has the rate gauge
    read the trading port's headroom."""
    from tests.unit.oms.test_handovers import _Store
    from tests.unit.oms.test_oms_runtime import World, started
    from tests.unit.test_oms_reconcile_wiring import Reads

    parked = Parked()
    held = functools.partial(StuckDetector, sleep=parked.sleep)  # the loop's waits, the test's
    monkeypatch.setattr(oms_detect_wiring, "StuckDetector", held)

    async def accounts(_env: str) -> tuple[UUID, ...]:
        return (ACCOUNT,)

    async def resolve(account_id: AccountId) -> AccountRef:  # a key the trading port takes
        return AccountRef(account_id=account_id, uid="u1", environment="demo", key_ref=KEY_REF)

    stores = DetectStores(
        reads=InMemoryStuckReads(), events=EventWriter(), account_ids=accounts, resolve=resolve,
        release=Released().release,
    )  # fmt: skip
    bus = Bus()
    sub = bus.subscribe("t", "demo.oms.incident", QueuePolicy.NEVER_DROP)
    world = World(handover_store=_Store(), reconcile_reads=Reads())
    for flag in world.flags:
        flag.read()
    async with started(_with_detection(world, stores, bus)) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
        assert math.isnan(_scraped(world.metrics, "entry"))  # no scan has run its chore yet
        runtime._standing.mark_stale(AccountId(ACCOUNT))
        parked.through(2)  # the poll for `ready`, then tick 0's jittered phase
        await asyncio.wait_for(parked.parked(3), 2)  # parked at its next tick: a scan ended
        assert ("oms.incident", "account_stale") in world.writer.actions
        published = await asyncio.wait_for(sub.get(), 2)
        assert isinstance(published, OmsIncident)
        assert (published.kind, published.account_id) == ("account_stale", ACCOUNT)
        assert _scraped(world.metrics, "entry") == FRESH_HEADROOM_TOKENS  # the port's headroom


async def test_without_its_stores_or_the_bus_the_runtime_composes_none() -> None:
    from tests.unit.oms.test_oms_runtime import World, started

    world = World()
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)
        assert runtime._composed().detect is None
        assert "stuck_detector" not in [name for name, _ in runtime._composed().closers]
