"""The private-stream consumer's composition (E29-T05 #848, S8a and S8b; 24-internal-schemas.md
Sec.8.12, 23-ws-protocol.md Sec.15.9, 20-architecture.md Sec.12.1): what `build_stream_consumer`
binds, the stand-ins it announces, the lockout's paging stand-in and the exchange-placed records,
the account notices' closed table and their producer check, the serving loop's hops, the wrappers
that raise nothing, the exchange-synced clock, the counts and the readiness hooks, and S8b's ports:
the streams on the account's port, account health's streamed accounts, the clock's epoch and the
owed gauge read at each scrape. Recording doubles only: no network, no sleeps, no live exchange."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast, get_args
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_stream_wiring as wiring
from candleviewer.account_health_wiring import TRACKING_REFRESH_S, StreamedAccountsUnread
from candleviewer.accounts.service import AccountHealthFeed
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import ClockDriftError
from candleviewer.exchange.base.models import AccountRef, Order, PrivateKind
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms import positions as position_stage
from candleviewer.oms import stream_consumer, stream_push
from candleviewer.oms.errors import (
    FreezeUnavailable,
    OmsNotReady,
    ProtectionReadingsUnavailable,
    ReconciliationUnavailable,
)
from candleviewer.oms.order_machine import OrderMachines
from candleviewer.oms.ports import (
    INTERIM_PORT_LABELS,
    INTERIM_PORTS_METRIC,
    AccountNoticeReason,
    CredentialRejections,
    Interim,
    NoHandoverStore,
    NoPositionProtection,
    NoReconciliation,
    RuntimePortName,
)
from candleviewer.oms.positions import PositionProjection
from candleviewer.oms.recorded_stop_stream import RecordedStopStream, Successor
from candleviewer.oms.repository import (
    OrderRepository,
    PositionRepository,
    PositionSnapshotRepository,
    RecordedStopRepository,
)
from candleviewer.oms.routing import TradingRouter
from candleviewer.oms.stream_consumer import (
    MAX_FUTURE_SKEW_US,
    NoPositionRows,
    refuse_live_without_position_rows,
)
from candleviewer.oms_lane import Serving
from candleviewer.oms_stream_wiring import (
    NOTICES,
    OWED_DEGRADED_S,
    ExchangeWallClock,
    PagedNoIntentRecords,
    PagingForeignOrderLockout,
    StreamWiring,
    account_notice,
    build_stream_consumer,
    checked_notice,
    refuse_live_without_freeze,
)
from candleviewer.oms_wiring import (
    SYSTEM_ACTOR,
    ClockHealthBinding,
    OmsAudit,
    OwnedAudit,
    TradingAccountsBinding,
)
from candleviewer.settings import Environment as ProcessEnvironment
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW
from candleviewer.ws.gateway import GatewayHub
from tests.unit.oms import position_rig
from tests.unit.oms.position_rig import ACCOUNT, NOW_US, position, routed
from tests.unit.oms.test_stream_push import event

A = ACCOUNT
SENTINEL = "sentinel-6b0d2e"  # a value that must never reach a log, a page or a frame
WALL = datetime(2026, 10, 26, 12, tzinfo=UTC)
RESYNCING: Final[AccountNoticeReason] = "oms.account_resyncing"


@dataclass
class World:
    """Every collaborator `build_stream_consumer` takes, recording into one ordered `trace`."""

    trace: list[str] = field(default_factory=list)
    emitted: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    pages: list[tuple[str, str]] = field(default_factory=list)
    notified: list[tuple[Callable[..., object], tuple[Any, ...]]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    reported: list[tuple[UUID, str]] = field(default_factory=list)
    raises: dict[str, BaseException] = field(default_factory=dict)
    offset: int | None = 250
    metrics: Metrics = field(default_factory=lambda: Metrics("demo"))
    #: The clock guard's health: what `assert_healthy` raises, None while it is healthy.
    drift: Exception | None = None
    #: What an account's environment's port answers a subscribe with.
    private_stream: object = field(default_factory=object)

    def build(self, **over: Any) -> StreamWiring:
        ports: dict[str, Any] = dict.fromkeys(("facade", "orders", "stops", "positions"), self)
        ports |= dict.fromkeys(("snapshots", "accounts", "trading", "ports"), self)
        ports |= dict.fromkeys(("health", "hub", "serving", "credentials", "audit"), self)
        ports |= {"emitter": self, "pager": self, "metrics": self.metrics, "clock_health": self}
        ports |= {"environment": ProcessEnvironment.DEMO, "now": lambda: WALL}
        ports |= {"offset_ms": lambda: self.offset, "wall_now": lambda: WALL}
        return build_stream_consumer(**(ports | over))

    def _hit(self, name: str) -> None:
        self.trace.append(name)
        if name in self.raises:
            raise self.raises[name]

    # the audit writer, the pager and the serving loop
    async def emit(self, action: str, **fields: Any) -> None:
        self._hit("emit")
        self.emitted.append((action, fields))

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self._hit("page")
        assert severity == "page"
        self.pages.append((machine_kind, summary))

    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None:
        self._hit("notify")
        assert not kwargs
        self.notified.append((fn, args))
        fn(*args)  # the serving loop runs it in arrival order

    # the gateway, account health and the credential report
    def broadcast_system(self, body: dict[str, Any]) -> int:
        self._hit("broadcast")
        self.frames.append(body)
        return 1

    def ws_heartbeat(self, account_id: UUID) -> None:
        self._hit("ws_heartbeat")
        self.evidence.append(("ws_heartbeat", (account_id,)))

    def ws_dropped(self, account_id: UUID) -> None:
        self._hit("ws_dropped")
        self.evidence.append(("ws_dropped", (account_id,)))

    def wallet_pushed(self, account_id: UUID, snapshot: object) -> bool:
        self._hit("wallet_pushed")
        self.evidence.append(("wallet_pushed", (account_id, snapshot)))
        return True

    async def refused(
        self, account_id: UUID, *, error_code: str, exchange_ret_code: int | None
    ) -> None:
        self._hit("refused")
        self.reported.append((account_id, error_code))

    # the lane's reads: the account, its port and the order store
    async def trading_account(self, account_id: AccountId) -> AccountRef:
        self._hit("trading_account")
        return AccountRef(account_id=account_id, uid="1", environment="demo", key_ref=str(A))

    def port_for(self, environment: str) -> World:
        self._hit(f"port_for:{environment}")
        return self

    history: list[Order] = field(default_factory=list)
    opened: list[Order] = field(default_factory=list)

    async def order_history(
        self, account: AccountRef, *, exchange_order_id: str | None = None
    ) -> Any:
        self._hit("order_history")
        return self.history

    async def open_orders(self, account: AccountRef, symbol: str | None = None) -> Any:
        self._hit("open_orders")
        return self.opened

    async def subscribe_private(self, account: AccountRef) -> Any:
        self._hit("subscribe_private")
        return self.private_stream

    # the clock guard's health (`ClockHealth.assert_healthy`), read in place
    def assert_healthy(self) -> None:
        if self.drift is not None:
            raise self.drift

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> Any:
        self._hit("get_by_exchange_order_id")

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> Any:
        self._hit("get_by_link_id")

    async def live_for_key(self, account_id: UUID, symbol: str, position_idx: int) -> Any:
        self._hit("live_for_key")
        return ()


def _gauge(metrics: Metrics, name: str, **labels: str) -> float | None:
    return metrics.registry.get_sample_value(name, {"env": metrics.env, **labels})


# --- what it binds ------------------------------------------------------------------------------


def test_wiring_binds_the_projection_never_no_position_rows() -> None:
    w = World().build()
    consumer = w.consumer
    assert isinstance(w.positions, PositionProjection)
    assert consumer._positions is w.positions
    assert not isinstance(consumer._positions, NoPositionRows)
    assert w.stops._positions is w.positions and w.successors._positions is w.positions
    assert consumer._pushes is w.pushes


def test_wiring_binds_the_recorded_stop_stream() -> None:
    world = World()
    w = world.build()
    assert isinstance(w.stops, RecordedStopStream) and w.pushes._stops is w.stops
    assert isinstance(w.successors, Successor) and w.pushes._successors is w.successors
    bound: tuple[object, ...] = (w.stops._machines, w.pushes._target, w.successors._audit)
    assert all(port is world for port in (*bound, cast(object, w.successors._stops)))
    assert w.successors._clock() == WALL  # the OMS's own clock, never the wall clock's offset
    assert w.positions._clock is w.clock and w.consumer._now_us == w.clock.now_us


def test_each_stand_in_is_announced_with_its_label() -> None:
    world = World()
    with capture_logs() as logs:
        w = world.build()
    labels: tuple[RuntimePortName, ...] = (
        "reconciliation", "execution_handovers", "protection_readings",
    )  # fmt: skip
    expected = (NoReconciliation, NoHandoverStore, NoPositionProtection)
    for label, kind in zip(labels, expected, strict=True):
        assert isinstance(w.stand_ins[label], kind)
    assert isinstance(w.stand_ins["foreign_order_lockout"], PagingForeignOrderLockout)
    names: tuple[RuntimePortName, ...] = (*labels, "foreign_order_lockout")
    for name in names:
        port = w.stand_ins[name]
        assert isinstance(port, Interim) and port.port == name and port.replaced_by
        assert _gauge(world.metrics, INTERIM_PORTS_METRIC, port=name) == 1.0
    warned = [log["port"] for log in logs if log["event"] == "oms_interim_port"]
    assert warned == list(names)
    assert w.pushes._lockout is w.stand_ins["foreign_order_lockout"]
    assert w.pushes._handovers is w.stand_ins["execution_handovers"]
    assert w.positions._readings is w.stand_ins["protection_readings"]
    assert w.consumer._recon is w.reconciliation is w.stand_ins["reconciliation"]


class RealPass:
    """A reconciliation port that is no stand-in."""

    async def request_reconciliation(self, account_id: UUID, *, reason: str) -> None:
        return None


class RealFreeze:
    """A foreign-order lockout that is no stand-in (E39-T04's freeze)."""

    async def open(self, account_id: AccountId, *, finding: str, key: str) -> None:
        return None


def test_a_real_port_named_in_place_of_a_stand_in_is_announced_at_zero() -> None:
    world = World()
    with capture_logs() as logs:
        w = world.build(reconciliation=RealPass(), lockout=RealFreeze())
    assert _gauge(world.metrics, INTERIM_PORTS_METRIC, port="reconciliation") == 0.0
    assert "reconciliation" not in [log.get("port") for log in logs]
    w.refuse_live(ProcessEnvironment.LIVE)  # a real pass and freeze, the projection: it runs
    live = World().build(
        reconciliation=RealPass(), lockout=RealFreeze(), environment=ProcessEnvironment.LIVE
    )
    assert isinstance(live, StreamWiring)


def test_a_live_build_with_a_stand_in_that_refuses_live_is_refused() -> None:
    with pytest.raises(ReconciliationUnavailable):  # never a consumer to start
        World().build(environment=ProcessEnvironment.LIVE)
    for env in (ProcessEnvironment.DEMO, ProcessEnvironment.TESTNET):
        World().build(environment=env)


def test_a_live_build_refuses_the_paging_lockout_even_with_a_real_pass() -> None:
    """The security sign-off on #848, condition M1: the paging foreign-order lockout records and
    pages a finding but cannot freeze its account (SR-E27-19), so a live build refuses it on the
    binding as bound, even where a real reconciliation pass leaves no other refusal before it;
    demo and testnet compose with it. The environment compares by value."""
    with pytest.raises(FreezeUnavailable):  # never a consumer to start
        World().build(reconciliation=RealPass(), environment=ProcessEnvironment.LIVE)
    for env in (ProcessEnvironment.DEMO, ProcessEnvironment.TESTNET):
        World().build(reconciliation=RealPass(), environment=env)
    paging = World().build().stand_ins["foreign_order_lockout"]
    with pytest.raises(FreezeUnavailable):
        refuse_live_without_freeze(cast(Any, "live"), paging)
    refuse_live_without_freeze(ProcessEnvironment.LIVE, RealFreeze())


# --- the lockout's stand-in and the exchange-placed records -------------------------------------


async def test_paging_lockout_writes_no_intent_detected_ahead_of_its_page_with_frozen_false() -> (
    None
):
    world = World()
    lockout = world.build().stand_ins["foreign_order_lockout"]
    assert isinstance(lockout, PagingForeignOrderLockout)
    await lockout.open(A, finding="execution", key="exec-1")
    assert world.trace == ["emit", "page"]  # written ahead, then paged
    [(action, fields)] = world.emitted
    assert action == "oms.no_intent_detected"
    assert fields["actor_label"] == SYSTEM_ACTOR and fields["actor_user_id"] is None
    assert (fields["object_kind"], fields["object_id"]) == ("exchange_account", str(A))
    assert fields["after_state"] == {
        "account_id": str(A), "finding": "execution", "key": "exec-1",
        "exchange_placed": False, "frozen": False,
    }  # fmt: skip
    assert (fields["env"], fields["reason"], fields["severity"]) == (
        "demo",
        "execution",
        "critical",
    )
    [(kind, summary)] = world.pages
    assert kind == "oms.foreign_order_lockout" and str(A) in summary
    await lockout.open(A, finding="execution", key="exec-1")  # open already: nothing more
    assert world.trace == ["emit", "page"]


async def test_paging_lockout_whose_record_fails_raises_before_any_page_and_opens_again() -> None:
    world = World(raises={"emit": RuntimeError(SENTINEL)})
    lockout = world.build().stand_ins["foreign_order_lockout"]
    assert isinstance(lockout, PagingForeignOrderLockout)
    with pytest.raises(RuntimeError):
        await lockout.open(A, finding="order", key="x1")
    assert world.pages == []  # the caller (`StreamPushes._open`) pages the failed lockout
    del world.raises["emit"]
    await lockout.open(A, finding="order", key="x1")  # not remembered: it opens on the next push
    assert world.trace == ["emit", "emit", "page"]


async def test_exchange_placed_records_write_exchange_placed_true_and_page() -> None:
    world = World()
    records = world.build().pushes._records
    assert isinstance(records, PagedNoIntentRecords)
    await records.exchange_placed(A, finding="order", key="x9")
    await records.exchange_placed(A, finding="order", key="x9")
    assert world.trace == ["emit", "page"]
    [(action, fields)] = world.emitted
    assert action == "oms.no_intent_detected"
    assert fields["after_state"]["exchange_placed"] is True
    assert fields["after_state"]["frozen"] is False
    assert world.pages[0][0] == "oms.stream_push"


async def test_one_key_opened_undecided_then_decided_is_recorded_for_each_finding() -> None:
    world = World()
    lockout = world.build().stand_ins["foreign_order_lockout"]
    assert isinstance(lockout, PagingForeignOrderLockout)
    await lockout.open(A, finding="undecided", key="exec-7")  # `execution.fast`, then `execution`
    await lockout.open(A, finding="execution", key="exec-7")
    await lockout.open(A, finding="execution", key="exec-7")
    findings = [fields["after_state"]["finding"] for _, fields in world.emitted]
    assert findings == ["undecided", "execution"] and len(world.pages) == 2


async def test_paged_keys_are_bounded_and_a_forgotten_one_pages_again() -> None:
    world = World()
    writer = wiring.NoIntentWriter(world, environment="demo")
    lockout = PagingForeignOrderLockout(writer, world, max_keys=2)
    for key in ("k1", "k2", "k3", "k1"):
        await lockout.open(A, finding="order", key=key)
    assert len(world.pages) == 4  # k1 was evicted by k3, so it pages once more, never less


async def test_a_failing_pager_never_unwinds_a_written_record() -> None:
    world = World(raises={"page": RuntimeError(SENTINEL)})
    lockout = world.build().stand_ins["foreign_order_lockout"]
    assert isinstance(lockout, PagingForeignOrderLockout)
    with capture_logs() as logs:
        await lockout.open(A, finding="order", key="x2")
    assert world.emitted and "stream_pager_failed" in [log["event"] for log in logs]
    assert SENTINEL not in repr(logs)
    del world.raises["page"]  # the lost page is not remembered: the next push pages, never less
    await lockout.open(A, finding="order", key="x2")
    assert world.trace == ["emit", "page", "emit", "page"] and len(world.pages) == 1
    await lockout.open(A, finding="order", key="x2")
    assert len(world.pages) == 1


def test_system_actor_is_the_oms_wirings() -> None:
    assert wiring.SYSTEM_ACTOR == SYSTEM_ACTOR


# --- the account notices (23 Sec.15.9) -----------------------------------------------------------


def test_notices_message_table_is_closed_and_names_no_account() -> None:
    assert dict(NOTICES) == {
        RESYNCING: (
            "warning",
            "An account is resynchronising; its orders and positions are being verified.",
        )
    }  # 23 Sec.15.9's table, E29-T05's one row
    body = account_notice(A, RESYNCING)
    assert body["message"] == NOTICES[RESYNCING][1] and str(A) not in body["message"]
    assert str(A) not in repr({k: v for k, v in body.items() if k != "exchange_account_ids"})
    for reason in ("oms.account_desync", "oms.account_stale", "oms.account_synced"):
        with pytest.raises(ValueError):  # E29-T06 adds its rows with its code
            account_notice(A, cast(Any, reason))


def test_notice_ids_are_a_list_of_canonical_lowercase_strings() -> None:
    world = World()
    world.build().consumer._notices.publish(A, reason=RESYNCING)
    [frame] = world.frames
    ids = frame["exchange_account_ids"]
    assert type(ids) is list and ids == [str(A)] and ids[0] == ids[0].lower()
    assert checked_notice(frame) == frame


@pytest.mark.parametrize(
    "change",
    [
        {"exchange_account_ids": {str(A)}},  # a set
        {"exchange_account_ids": (str(A),)},  # a tuple
        {"exchange_account_ids": [A]},  # a UUID object
        {"exchange_account_ids": []},  # none
        {"exchange_account_ids": [str(A).upper()]},  # not lowercase
        {"exchange_account_ids": ["not-a-uuid"]},
        {"message": f"Account {A} is resynchronising."},  # a message built from data
        {"severity": "info"},
        {"kind": "kill_switch"},
        {"label": "x"},  # a sixth key
    ],
)
def test_notice_producer_refuses_a_malformed_body(change: dict[str, Any]) -> None:
    body = account_notice(A, RESYNCING) | change
    with pytest.raises(ValueError) as refused:
        checked_notice(body)
    assert str(A) not in str(refused.value)


def test_notice_whose_check_refuses_it_is_never_offered_and_never_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    w = world.build()
    monkeypatch.setattr(wiring, "account_notice", lambda a, r: {"kind": "account_notice"})
    with capture_logs() as logs:
        w.consumer._notices.publish(A, reason=RESYNCING)
    assert world.frames == [] and world.notified == []
    assert [log["event"] for log in logs] == ["stream_notice_refused"]


# --- the hops, in order -------------------------------------------------------------------------


def test_health_and_notice_hops_go_through_serving_notify_in_order() -> None:
    world = World()
    w = world.build()
    health, notices, snapshot = w.consumer._health, w.consumer._notices, object()
    health.ws_heartbeat(A)
    health.ws_dropped(A)
    notices.publish(A, reason=RESYNCING)
    health.wallet_pushed(A, cast(Any, snapshot))
    assert [fn for fn, _ in world.notified] == [
        world.ws_heartbeat, world.ws_dropped, world.broadcast_system, world.wallet_pushed,
    ]  # fmt: skip
    assert [name for name in world.trace if name != "notify"] == [
        "ws_heartbeat", "ws_dropped", "broadcast", "wallet_pushed",
    ]  # fmt: skip
    assert world.trace.count("notify") == 4  # each one a notification, never a call
    assert world.evidence[-1] == ("wallet_pushed", (A, snapshot))


async def test_hops_go_to_the_serving_loop_from_the_lane_and_land_in_order() -> None:
    """The real `Serving` (`oms_lane`): from another thread each call is queued on the serving
    loop and lands there in the order the lane made it."""
    world = World()
    loop = asyncio.get_running_loop()
    w = world.build(serving=Serving(loop, world.metrics))

    def lane() -> None:
        w.consumer._health.ws_heartbeat(A)
        w.consumer._notices.publish(A, reason=RESYNCING)
        w.consumer._health.ws_dropped(A)

    await asyncio.to_thread(lane)
    async with asyncio.timeout(5):
        while len(world.trace) < 3:  # noqa: ASYNC110 - the queued callbacks, bounded above
            await asyncio.sleep(0)
    assert world.trace == ["ws_heartbeat", "broadcast", "ws_dropped"]


# --- the wrappers raise nothing (L-2) ------------------------------------------------------------


async def test_wrappers_raise_nothing_but_cancelled_error() -> None:
    world = World(raises={name: RuntimeError(SENTINEL) for name in ("notify", "refused")})
    w = world.build()
    with capture_logs() as logs:
        w.consumer._health.ws_heartbeat(A)
        w.consumer._health.ws_dropped(A)
        w.consumer._health.wallet_pushed(A, cast(Any, object()))
        w.consumer._notices.publish(A, reason=RESYNCING)
        w.consumer._notices.publish(A, reason=cast(Any, "oms.account_synced"))  # no row
        await w.consumer._credentials.refused(A, error_code="AUTH_ERROR", exchange_ret_code=None)
        w.metrics.push.count(cast(Any, "not-an-outcome"))
    events = [log["event"] for log in logs]
    assert events.count("stream_evidence_hop_failed") == 3
    assert events.count("stream_notice_refused") == 2
    assert "stream_auth_report_failed" in events and "stream_outcome_unbound" in events
    assert world.pages == [
        ("oms.stream_consumer", "a refused credential's report failed: RuntimeError")
    ]
    assert SENTINEL not in repr(logs) and SENTINEL not in repr(world.pages)

    class Cancelling:
        async def refused(self, account_id: UUID, **_kw: Any) -> None:
            raise asyncio.CancelledError

    guarded = world.build(credentials=Cancelling()).consumer._credentials
    with pytest.raises(asyncio.CancelledError):  # a cancel is never swallowed
        await guarded.refused(A, error_code="AUTH_ERROR", exchange_ret_code=None)


async def test_credential_report_reaches_the_runtimes_binding() -> None:
    world = World()
    await world.build().consumer._credentials.refused(
        A, error_code="AUTH_ERROR", exchange_ret_code=None
    )
    assert world.reported == [(A, "AUTH_ERROR")] and world.pages == []


# --- the clock (Q9) -----------------------------------------------------------------------------


def test_wall_clock_is_aware_and_offset_by_the_measured_skew() -> None:
    offset: list[int | None] = [None, None, 1_500, -250, None]
    clock = ExchangeWallClock(lambda: offset.pop(0), now=lambda: WALL)
    with capture_logs() as logs:
        unmeasured = [clock(), clock()]
        measured = [clock(), clock()]
        again = clock()
    assert unmeasured == [WALL, WALL]  # 0 while unmeasured
    assert measured == [WALL + timedelta(milliseconds=1_500), WALL - timedelta(milliseconds=250)]
    assert again == WALL
    assert all(t.tzinfo is not None and t.utcoffset() == timedelta(0) for t in measured)
    # one WARNING per unmeasured run: the first two calls are one run, the last a second
    assert [log["event"] for log in logs] == ["stream_wall_clock_unmeasured"] * 2


def test_wall_clock_reads_a_failed_offset_as_unmeasured_and_answers_microseconds() -> None:
    def broken() -> int | None:
        raise RuntimeError(SENTINEL)

    clock = ExchangeWallClock(broken, now=lambda: WALL)
    with capture_logs() as logs:
        assert clock() == WALL
    assert SENTINEL not in repr(logs)
    measured = ExchangeWallClock(lambda: 2, now=lambda: WALL)
    assert [log["event"] for log in logs] == ["stream_wall_clock_unmeasured"]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    assert measured.now_us() == (WALL - epoch) // timedelta(microseconds=1) + 2_000


def test_wall_clock_reads_an_offset_past_the_critical_drift_as_unmeasured() -> None:
    bound = inspect.signature(ClockGuard).parameters["hard_threshold_ms"].default
    assert wiring.MAX_OFFSET_MS == bound  # one bound: the clock guard's critical drift
    offset: list[int | None] = [bound, bound + 1, -(bound + 1), 10**15]
    clock = ExchangeWallClock(lambda: offset.pop(0), now=lambda: WALL)
    with capture_logs() as logs:
        reads = [clock() for _ in range(4)]  # 10**15 ms would overflow a `timedelta`
    assert reads == [WALL + timedelta(milliseconds=bound), WALL, WALL, WALL]
    assert [log["event"] for log in logs] == ["stream_wall_clock_unmeasured"]
    assert logs[0]["measured"] is True


def test_the_compositions_wall_clock_reads_the_injected_host_time() -> None:
    w = World().build(wall_now=lambda: WALL)
    assert w.clock() == WALL + timedelta(milliseconds=250)
    assert w.positions._clock() == WALL + timedelta(milliseconds=250)


def test_wall_clock_default_is_the_hosts_aware_utc_time() -> None:
    before = datetime.now(UTC)
    read = ExchangeWallClock(lambda: 0)()
    assert read.tzinfo is not None and before <= read <= datetime.now(UTC)
    assert read.astimezone(UTC) == read


# --- counts, the lag and readiness --------------------------------------------------------------


def test_counts_bind_closed_label_sets() -> None:
    world = World()
    w = world.build()
    sets = {
        "consumer": get_args(stream_consumer.Outcome.__value__),
        "push": get_args(stream_push.Outcome.__value__),
        "position": get_args(position_stage.Outcome.__value__),
    }
    stages = {"consumer": w.metrics.consumer, "push": w.metrics.push}
    stages["position"] = w.metrics.position
    for stage, counts in stages.items():
        assert counts.outcomes == sets[stage]
    assert w.consumer._counts is w.metrics.consumer and w.positions._counts is w.metrics.position
    assert w.pushes._counts is w.stops._counts is w.successors._counts is w.metrics.push
    [spec] = [s for s in CATALOGUE if s.name == "oms_stream_outcomes_total"]
    assert spec.labels == ("stage", "outcome")  # no account label
    assert sum(len(v) for v in sets.values()) <= spec.max_series
    counter = world.metrics.get("oms_stream_outcomes_total")
    assert counter.series_count == sum(len(v) for v in sets.values()) and not counter.breached
    w.metrics.push.count("no_intent")
    labels = {"stage": "push", "outcome": "no_intent"}
    assert _gauge(world.metrics, "oms_stream_outcomes_total", **labels) == 1.0
    w.metrics.push.count(cast(Any, "no_such_outcome"))
    assert counter.series_count == sum(len(v) for v in sets.values())  # never a new series


def test_lag_is_bound_per_closed_topic_and_drops_an_unknown_kind_or_a_negative_lag() -> None:
    world = World()
    w = world.build()
    assert set(w.metrics.lags) == set(get_args(PrivateKind.__value__))
    w.metrics.lag("order", 0.2)
    w.metrics.lag("order", -1.0)
    w.metrics.lag("ticker", 0.2)
    labels = {"topic": "order"}
    assert _gauge(world.metrics, "oms_stream_event_lag_seconds_count", **labels) == 1.0
    assert world.metrics.get("oms_stream_event_lag_seconds").series_count == 5


def test_metrics_catalogue_golden() -> None:
    specs = {s.name: s for s in CATALOGUE}
    rows = {
        name: (specs[name].kind, specs[name].labels, specs[name].max_series, specs[name].owner_epic)
        for name in ("oms_stream_event_lag_seconds", "oms_stream_outcomes_total")
    }
    rows["owed"] = (
        specs["oms_position_reading_owed_age_seconds"].kind,
        specs["oms_position_reading_owed_age_seconds"].labels,
        specs["oms_position_reading_owed_age_seconds"].max_series,
        specs["oms_position_reading_owed_age_seconds"].owner_epic,
    )
    assert rows == {
        "oms_stream_event_lag_seconds": ("histogram", ("topic",), 8, "E29"),
        "oms_stream_outcomes_total": ("counter", ("stage", "outcome"), 64, "E29"),
        "owed": ("gauge", (), 1, "E29"),
    }
    lag = specs["oms_stream_event_lag_seconds"].buckets
    assert lag is not None and 5.0 in lag and lag[-1] == 30.0  # the hand-over and silence bounds
    assert specs[INTERIM_PORTS_METRIC].max_series == len(INTERIM_PORT_LABELS) == 11


class Owed:
    def __init__(self) -> None:
        self.age, self.error = 0.0, False
        self.other: Exception | None = None

    def oldest_unhanded_age_s(self) -> float:
        if self.other is not None:
            raise self.other
        if self.error:
            raise RuntimeError("OrderedDict mutated during iteration")
        return self.age


class Fault:
    fault: str | None = None


def test_readiness_is_degraded_on_a_fault_or_an_owed_reading_past_its_bound() -> None:
    world = World()
    w = world.build()
    assert w.readiness._consumer is w.consumer and w.readiness._positions is w.positions
    owed, fault = Owed(), Fault()
    readiness = wiring.StreamReadiness(fault, owed, w.metrics.owed)
    assert readiness.degraded() is None
    owed.age = OWED_DEGRADED_S - 0.5
    assert readiness.degraded() is None
    assert _gauge(world.metrics, "oms_position_reading_owed_age_seconds") == OWED_DEGRADED_S - 0.5
    owed.age = OWED_DEGRADED_S
    assert readiness.degraded() == "a position reading has been owed to protection too long"
    owed.error = True  # a read that meets the lane's write keeps the last age
    assert readiness.owed_age_s() == OWED_DEGRADED_S
    owed.error, owed.other = False, ValueError(SENTINEL)  # any failure, never raised into /readyz
    with capture_logs() as logs:
        assert readiness.owed_age_s() == OWED_DEGRADED_S
        assert readiness.degraded() == "a position reading has been owed to protection too long"
    assert [log["error"] for log in logs] == ["ValueError", "ValueError"]
    assert SENTINEL not in repr(logs)
    owed.other = None
    fault.fault = "the consumer task ended"
    assert readiness.degraded() == "the private-stream consumer has faulted"
    assert w.readiness.degraded() is None and w.readiness.owed_age_s() == 0.0
    assert str(A) not in repr(readiness.degraded())


# --- S8b: the consumer's ports as the runtime binds them -----------------------------------------


async def test_port_streams_subscribe_on_the_accounts_environment_port() -> None:
    """24 Sec.8.12 "Its ports" (S8b): the consumer subscribes each account on its own
    environment's port (`TradingRouter.port_for`), the order lane's, whose stream source is the
    bridge to the serving loop's registry; never another environment's."""
    world = World()
    streams = world.build().consumer._streams
    assert isinstance(streams, wiring.PortStreams)
    ref = AccountRef(account_id=A, uid="1", environment="testnet", key_ref=str(A))
    assert await streams.subscribe(ref) is world.private_stream
    assert world.trace == ["port_for:testnet", "subscribe_private"]


async def test_health_accounts_are_account_healths_last_good_read_read_in_place() -> None:
    """S8b (the orchestrator's Q5): `StreamedAccounts` is account health's last good tracking
    read, one read in place from the lane and never a hop, so no stall of the serving loop faults
    the consumer; until health's boot pass it raises, which the consumer counts."""

    class Health:
        read: frozenset[UUID] | None = None

        def streamed(self) -> frozenset[UUID]:
            if self.read is None:
                raise StreamedAccountsUnread("not read yet")
            return self.read

    health = Health()
    accounts = wiring.HealthAccounts(health)
    with pytest.raises(StreamedAccountsUnread):
        await accounts.streamed_accounts()
    health.read = frozenset({A})
    assert await accounts.streamed_accounts() == {A}


async def test_health_accounts_answer_one_object_per_read_so_reads_are_told_apart() -> None:
    """24 Sec.8.12 (the delta's Minor 1): the set is answered as health holds it, never copied, so
    the same read answers the same object and health's next read a new one, even an equal one:
    the consumer holds an account its disable closed until that next read, by identity."""

    class Health:
        read = frozenset({A})

        def streamed(self) -> frozenset[UUID]:
            return self.read

    health = Health()
    accounts = wiring.HealthAccounts(health)
    first = await accounts.streamed_accounts()
    assert first is health.read and await accounts.streamed_accounts() is first
    health.read = frozenset({A})  # health's next read, equal to the last
    again = await accounts.streamed_accounts()
    assert again == first and again is not first and again is health.read


def test_clock_epoch_moves_only_on_an_unhealthy_to_healthy_edge() -> None:
    """S8b (the orchestrator's Q7): the epoch the consumer reads on each item moves once each time
    the exchange clock comes back into sync, a healthy read after one that was not, never on each
    healthy read; a read that raises anything at all is not healthy."""
    world = World()
    epochs = world.build().consumer._epochs
    assert isinstance(epochs, wiring.ClockEpoch)
    assert [epochs.epoch() for _ in range(3)] == [0, 0, 0]
    world.drift = ClockDriftError("past the hard threshold")
    assert epochs.epoch() == 0
    world.drift = None
    assert [epochs.epoch() for _ in range(3)] == [1, 1, 1]
    for drift in (OmsNotReady(), ValueError(SENTINEL)):  # unmeasured; anything at all
        world.drift = drift
        assert epochs.epoch() == 1
    world.drift = None
    assert epochs.epoch() == 2


def test_clock_epoch_over_no_clock_guard_never_moves() -> None:
    """A process that composes no clock guard reads none as healthy, so nothing re-applies: no
    clock means no re-sync."""
    epochs = wiring.ClockEpoch(ClockHealthBinding(None))
    assert [epochs.epoch() for _ in range(3)] == [0, 0, 0]


def test_the_consumer_takes_the_lag_the_host_clock_and_the_clock_epoch() -> None:
    """S8b binds what S8a left unbound: the lag on the metrics' histogram, the host's own clock
    for it, and the epoch over the clock guard's health."""
    world = World()
    w = world.build()
    assert w.consumer._lags is w.metrics and w.consumer._host_us == w.clock.host_us
    assert cast(wiring.ClockEpoch, w.consumer._epochs)._clock is world
    world.drift = ClockDriftError("x")
    assert w.consumer._epochs.epoch() == 0


def test_a_clock_the_caller_built_is_the_projections_and_the_consumers() -> None:
    """S8b: the runtime builds the position store over the exchange-synced clock and hands that
    same clock to the builder, so the store and the projection read one `ExchangeWallClock`."""
    clock = ExchangeWallClock(lambda: 7, now=lambda: WALL)
    w = World().build(clock=clock)
    assert w.clock is clock and w.positions._clock is clock
    assert w.consumer._now_us == clock.now_us and w.consumer._host_us == clock.host_us


def test_the_host_clock_carries_no_offset() -> None:
    """The lag's clock is the host's own, the one the adapter stamps `ts_ingest` on, with no
    measured offset: the venue's skew never moves the lag."""
    clock = ExchangeWallClock(lambda: 250, now=lambda: WALL)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    assert clock.host_us() == (WALL - epoch) // timedelta(microseconds=1)
    assert clock.now_us() == clock.host_us() + 250_000


def test_the_owed_gauge_is_read_at_each_scrape_from_bind_to_unbind() -> None:
    """S8b: from the consumer's start the owed gauge reads the projection at each scrape, never
    only when `/readyz` reads it; from its stop it reads 0, no longer the stopped projection."""
    world = World()
    w = world.build()
    owed = Owed()
    readiness = wiring.StreamReadiness(Fault(), owed, w.metrics.owed)
    owed.age = 42.0
    assert _gauge(world.metrics, wiring.OWED_AGE) == 0.0  # unbound: nothing set it
    readiness.bind()
    assert _gauge(world.metrics, wiring.OWED_AGE) == 42.0
    owed.age = 61.0
    assert _gauge(world.metrics, wiring.OWED_AGE) == 61.0
    readiness.unbind()
    assert _gauge(world.metrics, wiring.OWED_AGE) == 0.0


async def test_the_wiring_starts_then_binds_and_stops_then_unbinds() -> None:
    """`StreamWiring.start` starts the consumer, then binds the owed gauge; `stop` stops the
    consumer within its bound, then unbinds it; a start after the stop binds nothing."""
    world = World()
    w = world.build()
    cast(Any, w.positions).oldest_unhanded_age_s = lambda: 5.0  # a reading owed for 5 s
    w.start()
    assert w.consumer._task is not None
    assert _gauge(world.metrics, wiring.OWED_AGE) == 5.0
    await w.stop()
    assert w.consumer._task.done() and _gauge(world.metrics, wiring.OWED_AGE) == 0.0
    w.start()  # refused once stopped: the gauge stays unbound
    assert _gauge(world.metrics, wiring.OWED_AGE) == 0.0


# --- the lane's reads ---------------------------------------------------------------------------


def _order(xid: str, account: UUID = A) -> Order:
    """A transcribed order row (`test_stream_push.event`), as another order id and account."""
    made = event("order").payload
    assert isinstance(made, Order)
    return made.model_copy(update={"exchange_order_id": xid, "account_id": account})


async def test_fill_orders_read_the_history_then_the_open_orders_of_the_accounts_port() -> None:
    world = World()
    fills = world.build().pushes._fills
    other = _order("x1", account=UUID(int=0xB))
    world.history, world.opened = [other], [_order("x2"), _order("x1")]
    found = await fills.order_of(A, "x1", "BTCUSDT")
    assert found is not None and (found.account_id, found.exchange_order_id) == (A, "x1")
    assert world.trace == ["trading_account", "port_for:demo", "order_history", "open_orders"]
    world.trace.clear()
    world.history = [_order("x1")]
    assert await fills.order_of(A, "x1", "BTCUSDT") is not None
    assert "open_orders" not in world.trace
    world.history, world.opened = [], []
    assert await fills.order_of(A, "x3", "BTCUSDT") is None


async def test_stream_reads_bind_the_order_store_and_the_recorded_stop_facade() -> None:
    world = World()
    reads = world.build().pushes._reads
    await reads.get_by_exchange_order_id(A, "x")
    await reads.get_by_link_id(A, "l")
    assert await reads.live_for_key(A, "BTCUSDT", 0) == ()
    assert world.trace == ["get_by_exchange_order_id", "get_by_link_id", "live_for_key"]


# --- the carries --------------------------------------------------------------------------------


def test_max_future_skew_has_one_owner() -> None:
    assert MAX_FUTURE_SKEW_US == MAX_FUTURE_SKEW // timedelta(microseconds=1) == 5_000_000
    source = inspect.getsource(stream_consumer)
    assert "5_000_000" not in source and "MAX_FUTURE_SKEW // timedelta" in source


def test_the_consumers_refresh_is_account_healths_tracking_refresh() -> None:
    """24 Sec.8.12 "Its ports": the consumer reads the streamed accounts again on each of account
    health's tracking refreshes, so its own period is that one, pinned equal (two owners, one
    value), and the runtime's build keeps it."""
    assert stream_consumer.REFRESH_S == TRACKING_REFRESH_S
    assert World().build().consumer._refresh_s == TRACKING_REFRESH_S


def test_refuse_live_without_position_rows() -> None:
    with pytest.raises(ProtectionReadingsUnavailable):
        refuse_live_without_position_rows(ProcessEnvironment.LIVE, NoPositionRows())
    with pytest.raises(ProtectionReadingsUnavailable):  # by value: a plain "live" refuses too
        refuse_live_without_position_rows(cast(Any, "live"), NoPositionRows())
    for env in (ProcessEnvironment.DEMO, ProcessEnvironment.TESTNET):
        refuse_live_without_position_rows(env, NoPositionRows())
    w = World().build()
    refuse_live_without_position_rows(ProcessEnvironment.LIVE, w.positions)
    with pytest.raises(ReconciliationUnavailable):  # the stand-in, as bound, refuses live
        w.refuse_live(ProcessEnvironment.LIVE)
    w.refuse_live(ProcessEnvironment.DEMO)


# --- C-2.6 --------------------------------------------------------------------------------------


async def test_no_position_protection_pages_an_sl_lost_once_per_episode_through_the_wiring() -> (
    None
):
    """A lost stop no live order holds goes to the bound `NoPositionProtection`, which refuses it,
    so the projection pages P1 once per episode; the next `SL_OBSERVED` ends the episode."""
    rig = position_rig.Rig()
    world = World()
    w = world.build(
        facade=rig, orders=rig, stops=rig, positions=rig, snapshots=rig, pager=rig,
        offset_ms=lambda: 0,
    )  # fmt: skip
    assert w.clock() == WALL  # the host's time pinned, never the real one (C-13.7)
    lost = position()
    for _ in range(2):
        await w.positions.take(A, lost, routed(lost))
    assert len(rig.pages) == 1  # once per episode
    labels = {"stage": "position", "outcome": "reading_unavailable"}
    assert _gauge(world.metrics, "oms_stream_outcomes_total", **labels) == 2.0
    held = position(stop_loss=Decimal("60000"), updated_at=NOW_US + 200_000)
    await w.positions.take(A, held, routed(held))  # SL_OBSERVED: the episode ends
    again = position(updated_at=NOW_US + 300_000)
    await w.positions.take(A, again, routed(again))
    assert len(rig.pages) == 2


# --- the real types fit (mypy reads this; it never runs) -----------------------------------------


def _fits(
    machines: OrderMachines, orders: OrderRepository, stops: RecordedStopRepository,
    positions: PositionRepository, snapshots: PositionSnapshotRepository,
    accounts: TradingAccountsBinding, router: TradingRouter,
    health: AccountHealthFeed, hub: GatewayHub, serving: Serving,
    credentials: CredentialRejections, audit: OmsAudit, emitter: OwnedAudit, metrics: Metrics,
) -> StreamWiring:  # fmt: skip
    return build_stream_consumer(
        facade=machines, orders=orders, stops=stops, positions=positions, snapshots=snapshots,
        accounts=cast(Any, None), trading=accounts, ports=router, health=health, hub=hub,
        serving=serving, credentials=credentials, audit=audit,
        emitter=emitter, environment=ProcessEnvironment.DEMO, pager=cast(Any, None),
        metrics=metrics, now=lambda: WALL, offset_ms=lambda: None,
        clock_health=ClockHealthBinding(None),
    )  # fmt: skip
