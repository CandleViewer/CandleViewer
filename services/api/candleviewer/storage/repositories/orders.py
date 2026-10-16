"""Driver-free order and order-event store surface (E29-T01 #845 slice 2/3, `0029_oms_core`).

M14 (`oms`) may not import a storage driver (ADR-0003), so it types against `OrderStore` and
`OrderEventStore` and these frozen dataclasses; `orders_sqlalchemy.py` is the Postgres
implementation and `oms.repository` the M14 facade over it. Values use the column vocabulary of
`21-database-schema.md` Sec.3.3.4-3.3.5 (`'Buy'`, `'GTC'`, `'Full'`, ...); mapping them to the
24-internal-schemas.md Sec.8.1 models is the OMS's job.

Account scoping (C-12.4, #845 security notes): every read, and every write to an existing order,
takes the exchange account and the implementation re-checks it in SQL, so another account's order
reads as missing. The one unscoped call is `link_id_taken`: a yes/no over the global
`ux_orders_link`, which the 24 Sec.8.3 rule 5 collision check needs (#846 ruling Q1).

Money (AGENTS.md Sec.5.2: `Decimal`, never `float`): every numeric(38,18) value is a finite
`Decimal` that the column holds exactly. `require_money` refuses a float, an int, NaN (which numeric
stores and which passes every `> 0` CHECK), an infinity and any value the column would round, so
nothing is changed silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, Protocol, get_args, get_type_hints
from uuid import UUID

OrderState = Literal[
    "new", "pending_submit", "submitted", "accepted", "partially_filled", "filled",
    "pending_cancel", "cancelled", "pending_amend", "rejected", "expired", "untracked",
]  # fmt: skip
OrderIntent = Literal[
    "entry", "stop_loss", "take_profit", "scale_in", "scale_out", "flatten", "reverse",
    "algo_child",
]  # fmt: skip
OrderEventKind = Literal[
    "local_create", "submit_attempt", "ack", "reject", "fill", "partial_fill", "amend_request",
    "amend_ack", "cancel_request", "cancel_ack", "expire", "exchange_push", "reconcile_diff",
    "error",
]  # fmt: skip
OrderEventSource = Literal["local", "rest", "ws_private", "reconcile", "paper"]
OrderSide = Literal["Buy", "Sell"]
OrderType = Literal["Market", "Limit"]
TimeInForce = Literal["GTC", "IOC", "FOK", "PostOnly"]
TriggerBy = Literal["LastPrice", "MarkPrice", "IndexPrice"]
TpslMode = Literal["Full", "Partial"]
IdempotencyState = Literal["unsent", "in_flight", "acked", "failed"]

#: The `ix_orders_open` predicate: what `list_open` returns (a unit test pins the index).
OPEN_STATES: Final[frozenset[OrderState]] = frozenset(
    {
        "pending_submit",
        "submitted",
        "accepted",
        "partially_filled",
        "pending_cancel",
        "pending_amend",
    }
)
#: The unique index that makes `order_link_id` an idempotency key (21 Sec.3.3.4).
UX_ORDERS_LINK: Final = "ux_orders_link"
#: Upper bound of one `list_for_order` page.
MAX_EVENT_PAGE: Final = 500

_SCALE: Final = 18
_INTEGER_DIGITS: Final = 20  # numeric(38,18): 38 digits, 18 of them after the point


def require_money(column: str, value: Decimal) -> None:
    """Refuse what numeric(38,18) would not hold exactly; the error names the column only (the
    value is P1, 21 Sec.12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{column} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{column} must be a finite Decimal")
    if value.is_zero():
        return
    _, digits, exponent = value.as_tuple()
    significant = len(digits)
    while digits[significant - 1] == 0:  # non-zero, so a non-zero digit stops this
        significant -= 1
    lowest = int(exponent) + len(digits) - significant  # power of ten of the last non-zero digit
    if lowest < -_SCALE or significant + lowest > _INTEGER_DIGITS:
        raise ValueError(f"{column} does not fit numeric(38,18) without rounding")


def require_aware(column: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{column} must be a timezone-aware datetime")


def _check(row: object, money: tuple[str, ...], stamps: tuple[str, ...]) -> None:
    for name in money:
        value = getattr(row, name)
        if value is not None:
            require_money(name, value)
    for name in stamps:
        value = getattr(row, name)
        if value is not None:
            require_aware(name, value)


@dataclass(frozen=True, slots=True, kw_only=True)
class NewOrder:
    """An `orders` row to insert. The id is final (24 Sec.8.3 rules 1 and 4); `leaves_qty` and
    `created_ts` are the database's. The fill fields and `exchange_order_id` let reconciliation
    insert an adopted exchange order as it stands (21 Sec.3.3.4 "Adopted rows")."""

    id: UUID
    exchange_account_id: UUID
    order_link_id: str
    symbol: str
    side: OrderSide
    intent: OrderIntent
    order_type: OrderType
    qty: Decimal
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    trigger_by: TriggerBy | None = None
    trigger_direction: Literal[1, 2] | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tpsl_mode: TpslMode = "Full"
    time_in_force: TimeInForce = "GTC"
    reduce_only: bool = False
    close_on_trigger: bool = False
    position_idx: Literal[0, 1, 2] = 0
    state: OrderState = "new"
    trade_group_leg_id: UUID | None = None
    parent_order_id: UUID | None = None
    oco_group_ref: str | None = None
    exchange_order_id: str | None = None
    cum_exec_qty: Decimal = Decimal(0)
    cum_exec_value: Decimal = Decimal(0)
    avg_price: Decimal | None = None
    fee_paid: Decimal = Decimal(0)
    exchange_created_ts: datetime | None = None
    exchange_updated_ts: datetime | None = None
    is_paper: bool = False

    def __post_init__(self) -> None:
        _check(self, _NEW_ORDER_MONEY, _NEW_ORDER_STAMPS)


def _annotated(cls: type[NewOrder], kind: type) -> tuple[str, ...]:
    """The fields annotated `kind` or `kind | None`, read off the class, so none is missed."""
    hints = get_type_hints(cls)
    return tuple(name for name, hint in hints.items() if kind in (hint, *get_args(hint)))


_NEW_ORDER_MONEY: Final = _annotated(NewOrder, Decimal)
_NEW_ORDER_STAMPS: Final = _annotated(NewOrder, datetime)


@dataclass(frozen=True, slots=True, kw_only=True)
class NewOrderEvent:
    """An `order_events` row to append. The store assigns `seq` (0 for the first event, then the
    next per order) and the states, and redacts `payload`, `ret_code` and `ret_msg` before they
    are bound."""

    kind: OrderEventKind
    source: OrderEventSource
    event_ts: datetime
    payload: Mapping[str, object] = field(default_factory=dict)
    ret_code: str | None = None
    ret_msg: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        require_aware("event_ts", self.event_ts)


@dataclass(frozen=True, slots=True)
class OrderRow:
    """One `orders` row, every column (an explicit allow-list, pinned to the table by a test)."""

    id: UUID
    trade_group_leg_id: UUID | None
    exchange_account_id: UUID
    parent_order_id: UUID | None
    oco_group_ref: str | None
    order_link_id: str
    exchange_order_id: str | None
    symbol: str
    side: OrderSide
    intent: OrderIntent
    order_type: OrderType
    qty: Decimal
    price: Decimal | None
    trigger_price: Decimal | None
    trigger_by: TriggerBy | None
    trigger_direction: int | None
    take_profit: Decimal | None
    stop_loss: Decimal | None
    tpsl_mode: TpslMode
    time_in_force: TimeInForce
    reduce_only: bool
    close_on_trigger: bool
    position_idx: int
    state: OrderState
    cum_exec_qty: Decimal
    cum_exec_value: Decimal
    avg_price: Decimal | None
    leaves_qty: Decimal
    fee_paid: Decimal
    reject_code: str | None
    reject_message: str | None
    submit_attempts: int
    idempotency_state: IdempotencyState
    created_ts: datetime
    submitted_ts: datetime | None
    exchange_created_ts: datetime | None
    exchange_updated_ts: datetime | None
    last_reconciled_at: datetime | None
    is_paper: bool


@dataclass(frozen=True, slots=True)
class OrderEventRow:
    """One `order_events` row plus its order's `order_link_id`, the correlation key (ADR-0006
    rule 1). `payload`, `ret_code` and `ret_msg` are what was stored: the redacted values."""

    id: int
    order_id: UUID
    order_link_id: str
    seq: int
    kind: OrderEventKind
    from_state: OrderState | None
    to_state: OrderState | None
    source: OrderEventSource
    payload: dict[str, object]
    ret_code: str | None
    ret_msg: str | None
    latency_ms: int | None
    event_ts: datetime
    recv_ts: datetime


#: `OrderEventRow` fields that are `order_events` columns (all but the joined link id).
EVENT_FIELDS: Final = tuple(f.name for f in fields(OrderEventRow) if f.name != "order_link_id")


class OrderStoreError(Exception):
    """Base for order store errors."""


class OrderConstraintError(OrderStoreError):
    """The database refused the write by a named constraint (`ux_orders_link`, `ord_cum`, ...).

    Carries the name only, never a value (C-12.6)."""

    def __init__(self, constraint: str) -> None:
        super().__init__(f"order write violates constraint {constraint!r}")
        self.constraint = constraint


class OrderNotFoundError(OrderStoreError):
    """No such order in this account; another account's order is indistinguishable."""


class OrderStore(Protocol):
    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        """Insert the order and its first event (`seq` 0, `to_state` the order's state) in one
        statement, so one round trip in one transaction (#845 performance notes)."""
        ...

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        """The account's orders in `OPEN_STATES`, oldest first. Not paged: reconciliation needs
        every open order, and the exchange caps the active orders per symbol."""
        ...

    async def link_id_taken(self, order_link_id: str) -> bool:
        """Whether any row, of any account, in any state, holds the id (24 Sec.8.3 rule 5)."""
        ...


class OrderEventStore(Protocol):
    async def append(self, account_id: UUID, order_id: UUID, event: NewOrderEvent) -> OrderEventRow:
        """Append with the next `seq`, under a lock on the order row; no state transition
        (`from_state`, `to_state` NULL). `OrderNotFoundError` outside the account."""
        ...

    async def list_for_order(
        self, account_id: UUID, order_id: UUID, *, after_seq: int = -1, limit: int = MAX_EVENT_PAGE
    ) -> tuple[OrderEventRow, ...]:
        """Events with `seq > after_seq`, in `seq` order; empty outside the account."""
        ...
