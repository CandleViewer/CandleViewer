"""A rig for the OMS's command port (E29-T04 #913): `OmsCommandPort` over a demo and a live
`FakeTradingPort` routed by environment, the in-memory order and recorded-stop stores, and recording
doubles of its other ports (the notice route is `order_rig`'s `Notices`). Shared by
`test_commands.py` and B1's contract test `tests/xstate_contract/test_b01_order_commands.py`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from candleviewer.domain.primitives import AccountId, Environment, GroupId, Side
from candleviewer.exchange.base.errors import ServiceUnavailableError
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, Order, Position, RateLane
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.clock_halt import ClockHalt
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.errors import HandoverUnavailable, TradingDisabled
from candleviewer.oms.fakes import (
    FakeClockHealth,
    InMemoryOrderStore,
    InMemoryRecordedStopStore,
    InMemoryTradingAccounts,
)
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_machine import OrderAuditRecord, _order_fields
from candleviewer.oms.ports import (
    ClockHealth,
    KeyedRecord,
    OrderHandovers,
    RequestRecord,
    StopRequestGate,
    SubmitAudit,
    TradingAccounts,
)
from candleviewer.oms.repository import OrderRepository, RecordedStopRepository
from candleviewer.oms.routing import TradingRouter
from candleviewer.oms.stop_gate import ResolvingStopGate, StopVoidAudit
from candleviewer.oms.stop_resolution import CompleteRead, StopResolver
from candleviewer.oms_wiring import STOP_REQUEST_BOUND_S
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.orders import (
    ORDER_STATE_OF,
    LifecycleState,
    NewOrder,
    NewOrderEvent,
    OrderRow,
)
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop
from tests.unit.oms.order_rig import Notices

ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
LIVE_ACCOUNT = AccountId(UUID("6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"))
GROUP = GroupId(UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"))
KEYS: Mapping[Environment, str] = {
    "demo": "00000000-0000-4000-8000-0000000000d1",
    "live": "00000000-0000-4000-8000-0000000000e1",
}
UIDS: Mapping[Environment, str] = {"demo": "100001", "live": "200001"}
SYMBOL = "BTCUSDT"
STOP = Decimal("58000")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
T0_US = (T0 - EPOCH) // timedelta(microseconds=1)
HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
LANE_WAITS: dict[RateLane, float] = {"critical": 5.0, "entry": 0.75, "poll": 5.0}
type AnyRecord = OrderAuditRecord | KeyedRecord | RequestRecord


def outage(ret_code: int = 10019) -> ServiceUnavailableError:
    """The venue's outage as the exchange port raises it (#4092, #2863): 10016 or 10019 off a
    create, once the client's attempts are spent."""
    return ServiceUnavailableError("the venue is restarting", exchange_ret_code=ret_code)


def ref(account_id: AccountId = ACCOUNT, environment: Environment = "demo") -> AccountRef:
    return AccountRef(
        account_id=account_id,
        uid=UIDS[environment],
        environment=environment,
        key_ref=KEYS[environment],
    )


def link(account_id: AccountId = ACCOUNT, environment: Environment = "demo", seq: int = 0) -> str:
    """A generated id of the account and environment, as the fake port takes one (24 Sec.8.3)."""
    return OrderLinkIdParts.generate(
        mode="exchange",
        environment=environment,
        group_id=GROUP,
        account_id=account_id,
        seq=seq,
        purpose="entry",
    ).value


def new_order(
    account_id: AccountId = ACCOUNT, environment: Environment = "demo", *, seq: int = 0, **over: Any
) -> NewOrder:
    """A limit buy entry with its stop and take-profit, `validated` as the pipeline builds it."""
    order_link_id = link(account_id, environment, seq)
    base = NewOrder(
        id=uuid5(NAMESPACE_URL, order_link_id),
        exchange_account_id=account_id,
        order_link_id=order_link_id,
        symbol=SYMBOL,
        side="Buy",
        intent="entry",
        order_type="Limit",
        qty=Decimal("0.010"),
        price=Decimal("60000"),
        stop_loss=STOP,
        take_profit=Decimal("64000"),
        state="pending_submit",
        lifecycle_state="validated",
    )
    return replace(base, **over)


def view(order: NewOrder | OrderRow, **over: Any) -> dict[str, Any]:
    """B1's view of the order as a command carries it: the VALIDATE fields the facade sends
    (`_order_fields`), stamped as B1 stamps them, through `b01._view`."""
    as_new = order if isinstance(order, NewOrder) else _as_new(order)
    context = b01._order(_order_fields(as_new)) | {"filled_qty": "0", "exchange_order_id": None}
    return b01._view(context) | over


def _as_new(row: OrderRow) -> NewOrder:
    return NewOrder(
        id=row.id,
        exchange_account_id=row.exchange_account_id,
        order_link_id=row.order_link_id,
        symbol=row.symbol,
        side=row.side,
        intent=row.intent,
        order_type=row.order_type,
        qty=row.qty,
        price=row.price,
        trigger_price=row.trigger_price,
        take_profit=row.take_profit,
        stop_loss=row.stop_loss,
        reduce_only=row.reduce_only,
    )


def command(
    kind: b01.CommandKind,
    order: NewOrder | OrderRow,
    terms: Mapping[str, Any] | None = None,
    **over: Any,
) -> b01.Command:
    return b01.Command(
        kind=kind,
        key=f"{order.order_link_id}:{kind}:1",
        order=view(order, **over),
        terms=dict(terms or {}),
    )


def exchange_order(order: NewOrder, *, state: str = "new", **over: Any) -> Order:
    """The venue's order under `order`'s id, every SR-E29-03 field the row's, `over` aside."""
    fields: dict[str, Any] = {
        "order_link_id": order.order_link_id,
        "exchange_order_id": f"x-{order.order_link_id[-8:]}",
        "account_id": order.exchange_account_id,
        "symbol": order.symbol,
        "side": order.side.lower(),
        "order_type": order.order_type.lower(),
        "qty": order.qty,
        "price": order.price,
        "state": state,
        "filled_qty": Decimal(0),
        "leaves_qty": order.qty,
        "avg_fill_price": None,
        "created_at": T0_US,
        "terminal_at": None,
        "reduce_only": order.reduce_only,
        "trigger_price": order.trigger_price,
        "stop_loss": order.stop_loss,
        "take_profit": order.take_profit,
    }
    return Order.model_validate(fields | over)


def position(
    account_id: AccountId = ACCOUNT,
    *,
    side: Side | None = "buy",
    qty: str = "0.010",
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
    updated_at: int = T0_US,
    position_idx: Literal[0, 1, 2] = 0,
) -> Position:
    return Position(
        account_id=account_id,
        symbol=SYMBOL,
        position_idx=position_idx,
        side=side,
        qty=Decimal(qty),
        avg_entry_price=Decimal("60000"),
        mark_price=Decimal("60100"),
        liq_price=None,
        leverage=Decimal("10"),
        unrealised_pnl=Decimal("1"),
        cum_realised_pnl=Decimal("0"),
        take_profit=take_profit,
        stop_loss=stop_loss,
        trailing_stop_distance=None,
        updated_at=updated_at,
    )


@dataclass
class Now:
    """The port's wall clock, in microseconds, which a test moves."""

    us: int = T0_US

    def __call__(self) -> int:
        return self.us


@dataclass
class Monotonic:
    """The clock halt's monotonic clock, in seconds."""

    s: float = 100.0

    def __call__(self) -> float:
        return self.s


@dataclass
class Audits:
    """`OrderAudit` and `SubmitAudit` in one: each record lands in `written` with the count of
    exchange calls made before it (`sent_before`); `refuse` raises instead. The pipeline's
    request records (`RequestRecord`) land here too (`submit_rig`)."""

    sent: Callable[[], int] = lambda: 0
    written: list[tuple[AnyRecord, int]] = field(default_factory=list)
    refuse: BaseException | None = None

    def record_id(self, action: str, name: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"{action}:{name}")

    async def write(self, record: AnyRecord) -> None:
        if self.refuse is not None:
            raise self.refuse
        self.written.append((record, self.sent()))

    def actions(self) -> list[tuple[str, str]]:
        return [(record.action, record.reason) for record, _ in self.written]


@dataclass
class Handovers:
    """A recording `OrderHandovers`; `refuse` makes every hand-over `HandoverUnavailable`."""

    handed: list[tuple[AccountId, str]] = field(default_factory=list)
    refuse: bool = False

    async def hand_over_order(self, account_id: AccountId, order: Order) -> None:
        if self.refuse:
            raise HandoverUnavailable("refused by the test")
        self.handed.append((account_id, order.exchange_order_id))


@dataclass
class Credentials:
    """A recording `CredentialRejections`."""

    calls: list[tuple[AccountId, str, int | None]] = field(default_factory=list)

    async def refused(
        self, account_id: AccountId, *, error_code: str, exchange_ret_code: int | None
    ) -> None:
        self.calls.append((account_id, error_code, exchange_ret_code))


@dataclass
class Switches:
    """`TradingSwitches` answering a refusal set per account."""

    refusals: dict[AccountId, TradingDisabled] = field(default_factory=dict)
    asked: list[tuple[AccountId, Environment]] = field(default_factory=list)

    def refusal(self, account_id: AccountId, environment: Environment) -> TradingDisabled | None:
        self.asked.append((account_id, environment))
        return self.refusals.get(account_id)


@dataclass
class Rig:
    port: OmsCommandPort
    demo: FakeTradingPort
    live: FakeTradingPort
    store: InMemoryOrderStore
    orders: OrderRepository
    stops: RecordedStopRepository
    accounts: InMemoryTradingAccounts
    audits: Audits
    handovers: OrderHandovers
    credentials: Credentials
    switches: Switches
    health: FakeClockHealth
    halt: ClockHalt
    now: Now
    monotonic: Monotonic
    notices: Notices
    metrics: Metrics
    gate: StopRequestGate

    def calls(self, port: FakeTradingPort | None = None) -> list[str]:
        return [call.method for call in (port or self.demo).calls]

    async def stored(
        self, order: NewOrder, *, lifecycle: LifecycleState = "submitting"
    ) -> OrderRow:
        """`order` stored as a restart finds it, in `lifecycle` (its `orders` state alike)."""
        row = replace(order, state=ORDER_STATE_OF[lifecycle], lifecycle_state=lifecycle)
        event = NewOrderEvent(kind="submit_attempt", source="local", event_ts=T0)
        return await self.orders.create(row, event)


def build_rig(
    *,
    handovers: OrderHandovers | None = None,
    gate: StopRequestGate | None = None,
    created_at: Callable[[], datetime] = lambda: T0,
    clock: ClockHealth | None = None,
    **port_kwargs: Any,
) -> Rig:
    """`clock` is what the halt reads, by default the rig's measured `health`."""
    now, monotonic = Now(), Monotonic()
    demo = FakeTradingPort(environment="demo", now_us=now)
    live = FakeTradingPort(environment="live", now_us=now)
    store = InMemoryOrderStore(clock=created_at)
    orders = OrderRepository(store)
    stops = RecordedStopRepository(InMemoryRecordedStopStore(store))
    accounts = InMemoryTradingAccounts(ref(), ref(LIVE_ACCOUNT, "live"))
    audits = Audits(sent=lambda: len(demo.calls) + len(live.calls))
    chosen = handovers if handovers is not None else Handovers()
    credentials, switches = Credentials(), Switches()
    health = FakeClockHealth(monotonic)
    health.measure()
    metrics = Metrics("demo")
    halt = ClockHalt(health if clock is None else clock, monotonic=monotonic, metrics=metrics)
    notices = Notices()
    router = TradingRouter({"demo": demo, "live": live}, lane_waits=LANE_WAITS)

    def at() -> datetime:  # the port's clock
        return EPOCH + timedelta(microseconds=now.us)

    if gate is None:
        gate = stop_gate(stops, orders, audits, accounts, router, at, monotonic, metrics)
    port = OmsCommandPort(
        router=router,
        accounts=accounts,
        orders=orders,
        stops=stops,
        handovers=chosen,
        credentials=credentials,
        clock_halt=halt,
        switches=switches,
        audit=audits,
        submit_audit=audits,
        gate=gate,
        notices=notices,
        now_us=now,
        **port_kwargs,
    )
    return Rig(
        port, demo, live, store, orders, stops, accounts, audits, chosen, credentials, switches,
        health, halt, now, monotonic, notices, metrics, gate,
    )  # fmt: skip


def stop_gate(
    stops: RecordedStopRepository,
    orders: OrderRepository,
    audit: SubmitAudit,
    accounts: TradingAccounts,
    router: TradingRouter,
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    metrics: Metrics,
) -> ResolvingStopGate:
    """The runtime's stop-request gate (S3-H) over a rig's stores and router, its startup floor
    long past, so each row waits only past its request's bound."""
    resolver = StopResolver(stops, CompleteRead(orders), StopVoidAudit(audit), now=now)
    return ResolvingStopGate(
        stops, resolver, accounts=accounts, port_for=router.port_for,
        bound_s=STOP_REQUEST_BOUND_S, now=now, monotonic=monotonic, metrics=metrics,
        started_at=EPOCH,
    )  # fmt: skip


async def earlier_request(rig: Rig, source: Any = "trading_stop") -> None:
    """A trading-stop request of the key (or a restore), in flight since `T0`, the store's clock."""
    earlier = NewRecordedStop(
        id=uuid5(NAMESPACE_URL, "earlier"),
        exchange_account_id=ACCOUNT,
        symbol=SYMBOL,
        position_idx=0,
        position_side="Buy",
        kind="stop_loss",
        source=source,
        order_id=None,
        tpsl_mode="Full",
        trigger_price=Decimal("57000"),
        size=None,
        audit_record_id=uuid5(NAMESPACE_URL, "earlier-record"),
        actor_user_id=None,
    )

    async def audited(_rows: Any) -> None:
        return None

    await rig.stops.record([earlier], write_ahead=audited)
