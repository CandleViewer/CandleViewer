"""Driver-free order and order-event store surface (E29-T01 #845, `0029_oms_core`).

M14 (`oms`) may not import a storage driver (ADR-0003), so it types against `OrderStore` and
`OrderEventStore` and these frozen dataclasses; `orders_sqlalchemy.py` is the Postgres
implementation and `oms.repository` the M14 facade over it. Values use the column vocabulary of
`21-database-schema.md` Sec.3.3.4-3.3.5 (`'Buy'`, `'GTC'`, `'Full'`, ...); mapping them to the
24-internal-schemas.md Sec.8.1 models is the OMS's job.

Account scoping (C-12.4, #845 security notes): every read, and every write to an existing order,
takes the exchange account and the implementation re-checks it in SQL, so another account's order
reads as missing. Two calls are unscoped: `link_id_taken`, a yes/no over the global
`ux_orders_link`, which the 24 Sec.8.3 rule 5 collision check needs (#846 ruling Q1); and
`list_unfinished`, which only the OMS runtime's startup hydration reads (E29-T04), behind a callers
fence (`tests/unit/architecture/test_oms_system_reads_callers.py`). The exit routes' two reads
(E29-T04 slice 4, `get_in_scope` and `accounts_in_scope`) take the principal's `AccountScope`
instead, held in SQL by one predicate, the scope written once (C-12.4).

Money (AGENTS.md Sec.5.2: `Decimal`, never `float`): every numeric(38,18) value is a finite
`Decimal` that the column holds exactly. `require_money` refuses a float, an int, NaN (which numeric
stores and which passes every `> 0` CHECK), an infinity and any value the column would round, so
nothing is changed silently.

Writes here are the insert of an order with its first event (`OrderStore.create`) and the append of
an event without a state transition (`OrderEventStore.append`). Updates of an existing order
(state, fills, reject fields) with events that carry `from_state`/`to_state` are E29-T03's
write-ahead step (`transition`, `ExecutionStore.commit_fill`); E29-T04 adds the 24 Sec.8.4 columns.
`state` is the persisted form of the B1 chart's state (`ORDER_STATE_OF`), and `lifecycle_state`
(`0034`) the chart state verbatim. `create` and every step set it with `state` when the caller
names it, as B1's write-ahead step always does (E29-T03 #847, `oms.order_steps`), and both stores
refuse a pair that `ORDER_STATE_OF` does not map; a row written without it keeps NULL.

For the OMS (24 Sec.8.2 S7): an exception from any call means its write is not confirmed. The OMS
does not accept the order and sends nothing under its id; a commit cut off by a lost connection
may still have stored the row, and the id then reads as taken (`link_id_taken`), so the next
attempt allocates another (24 Sec.8.3 rule 5). The store caps each statement but not opening a
connection or waiting for the pool, so the OMS bounds every call with `asyncio.timeout`
(`.claude/rules/20-python-backend.md`).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal, Protocol, get_args, get_type_hints
from uuid import UUID

from candleviewer.domain.primitives import Environment
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.exchange_payload import MAX_CODE_CHARS, redact_exchange_text

OrderState = Literal[
    "new", "pending_submit", "submitted", "accepted", "partially_filled", "filled",
    "pending_cancel", "cancelled", "pending_amend", "rejected", "expired", "untracked",
    "triggered", "unknown", "quarantined", "killed", "held",
]  # fmt: skip
#: The B1 order chart's `lifecycle` states, verbatim (`order_lifecycle_state`, 28 B1).
LifecycleState = Literal[
    "draft", "validated", "submitting", "submitted", "triggered", "partially_filled",
    "cancel_pending", "amend_pending", "unknown", "quarantined", "untracked", "held", "filled",
    "cancelled", "rejected", "expired", "killed",
]  # fmt: skip
OrderIntent = Literal[
    "entry", "stop_loss", "take_profit", "scale_in", "scale_out", "flatten", "reverse",
    "algo_child",
]  # fmt: skip
OrderEventKind = Literal[
    "local_create", "submit_attempt", "ack", "reject", "fill", "partial_fill", "amend_request",
    "amend_ack", "cancel_request", "cancel_ack", "expire", "exchange_push", "reconcile_diff",
    "error", "kill", "adopt",
]  # fmt: skip
OrderEventSource = Literal["local", "rest", "ws_private", "reconcile", "paper"]
FillRefusal = Literal["above_qty", "paper_mismatch", "state_mismatch"]
OrderSide = Literal["Buy", "Sell"]
OrderType = Literal["Market", "Limit"]
TimeInForce = Literal["GTC", "IOC", "FOK", "PostOnly"]
TriggerBy = Literal["LastPrice", "MarkPrice", "IndexPrice"]
TpslMode = Literal["Full", "Partial"]
IdempotencyState = Literal["unsent", "in_flight", "acked", "failed"]
#: How the row came to exist (21 Sec.3.3.4 `ord_provenance`, 22 `OrderProvenance`), set at insert
#: and never changed: the OMS's own submission, a reconciliation adoption, or a recorded stop's
#: TP/SL order (24 Sec.8.3 rule 7).
OrderProvenance = Literal["placed", "reconciliation", "recorded_stop"]
#: How a step settles its entry's recorded stops (21 Sec.3.3.11's table, E29-T04): `answered` once
#: the entry is accepted or fills, `void` only once the exchange confirms it ended unfilled; a step
#: that leaves them waiting for the complete read (24 Sec.8.8 rule 6) names neither.
EntryStopSettle = Literal["answered", "void"]

#: 24-internal-schemas.md Sec.8.2: the `order_state` value that persists each chart state. One to
#: one; six names differ, and `submitted` names a different state on each side, so a reader of
#: `orders` takes the chart's state from `lifecycle_state` (`ord_lifecycle` admits these pairs
#: only). `order_events` keeps this value alone: a reader of events maps it back through
#: `LIFECYCLE_STATE_OF`.
ORDER_STATE_OF: Final[Mapping[LifecycleState, OrderState]] = MappingProxyType({
    "draft": "new", "validated": "pending_submit", "submitting": "submitted",
    "submitted": "accepted", "triggered": "triggered", "partially_filled": "partially_filled",
    "cancel_pending": "pending_cancel", "amend_pending": "pending_amend", "unknown": "unknown",
    "quarantined": "quarantined", "untracked": "untracked", "held": "held", "filled": "filled",
    "cancelled": "cancelled", "rejected": "rejected", "expired": "expired", "killed": "killed",
})  # fmt: skip
#: The inverse of `ORDER_STATE_OF` (21-database-schema.md Sec.3.3.5): the chart state each
#: `order_state` value persists, which E29-T03's rebuild of an order from its `order_events` reads
#: off each event's `to_state`. Exact, as the map is one to one.
LIFECYCLE_STATE_OF: Final[Mapping[OrderState, LifecycleState]] = MappingProxyType(
    {stored: chart for chart, stored in ORDER_STATE_OF.items()}
)
#: The `ix_orders_open` predicate: what `list_open` returns (a unit test pins the index). Neither
#: `untracked` nor `held` is open: B1 treats both as orders the OMS does not own (INV-B1-n).
OPEN_STATES: Final[frozenset[OrderState]] = frozenset(
    {
        "pending_submit",
        "submitted",
        "accepted",
        "partially_filled",
        "pending_cancel",
        "pending_amend",
        "triggered",
        "unknown",
        "quarantined",
    }
)
#: What `list_unfinished` returns (21 Sec.13.1 row 49): the open set, `held` and `untracked`, every
#: state of an order that is not final but `new` (B1's `draft`, which is never stored).
UNFINISHED_STATES: Final = OPEN_STATES | frozenset[OrderState]({"held", "untracked"})
#: The sources of a step the exchange reported, which carries the exchange's message (OM-R02).
EXCHANGE_SOURCES: Final = frozenset[OrderEventSource]({"rest", "ws_private", "reconcile"})
#: The kinds of a fill's event, which only a fill's step writes, with its execution (OM-R02).
FILL_KINDS: Final = frozenset[OrderEventKind]({"fill", "partial_fill"})
#: The values a step's `from_state`, `to_state`, `kind` and `source` may take (OM-T04).
_LITERALS: Final = tuple(map(get_args, (OrderState, OrderState, OrderEventKind, OrderEventSource)))
_IDEMPOTENCY_STATES: Final = frozenset(get_args(IdempotencyState))
_ENTRY_STOP_SETTLES: Final = frozenset(get_args(EntryStopSettle))
#: The order terms an accepted amend may change (22-api-openapi.yaml `AmendOrderRequest`).
AMENDABLE: Final = ("qty", "price", "trigger_price", "take_profit", "stop_loss")
#: The unique index that makes `order_link_id` an idempotency key (21 Sec.3.3.4).
UX_ORDERS_LINK: Final = "ux_orders_link"
#: Upper bound of one `list_for_order` page.
MAX_EVENT_PAGE: Final = 500
#: The exchange's order id, 1 to 64 characters, as the adapter's `ExchangeOrderId` (a test pins it).
MAX_EXCHANGE_ORDER_ID_CHARS: Final = 64


def require_money(column: str, value: Decimal, precision: int = 38, scale: int = 18) -> None:
    """Refuse what numeric(precision, scale), numeric(38,18) unless given, would not hold exactly;
    the error names the column only (the value is P1, 21 Sec.12)."""
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
    if lowest < -scale or significant + lowest > precision - scale:
        raise ValueError(f"{column} does not fit numeric({precision},{scale}) without rounding")


def require_aware(column: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{column} must be a timezone-aware datetime")


def require_limit(limit: int) -> None:
    """A read's bound on its rows (C-2.18): an int of at least 1, never a bool."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be an int of at least 1")


def require_exchange_order_id(value: object) -> None:
    """`ValueError`, before any statement, unless `value` is text of 1 to
    `MAX_EXCHANGE_ORDER_ID_CHARS` characters: `None` would read `IS NULL`, an arbitrary unbound
    row. Names no value."""
    if not (isinstance(value, str) and 1 <= len(value) <= MAX_EXCHANGE_ORDER_ID_CHARS):
        raise ValueError(f"an order id is text of 1 to {MAX_EXCHANGE_ORDER_ID_CHARS} characters")


def check_fields(
    row: object, money: Mapping[str, tuple[int, int]], stamps: tuple[str, ...]
) -> None:
    """`require_money` on each set field of `money` (name to precision and scale), and
    `require_aware` on each set field of `stamps`."""
    for name, (precision, scale) in money.items():
        value = getattr(row, name)
        if value is not None:
            require_money(name, value, precision, scale)
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
    lifecycle_state: LifecycleState | None = None
    provenance: OrderProvenance = "placed"

    def __post_init__(self) -> None:
        check_fields(self, _NEW_ORDER_MONEY, _NEW_ORDER_STAMPS)
        require_lifecycle(self.lifecycle_state, self.state)


def typed_fields(cls: type, kind: type) -> tuple[str, ...]:
    """The fields annotated `kind` or `kind | None`, read off the class, so none is missed."""
    hints = get_type_hints(cls)
    return tuple(name for name, hint in hints.items() if kind in (hint, *get_args(hint)))


_NEW_ORDER_MONEY: Final = dict.fromkeys(typed_fields(NewOrder, Decimal), (38, 18))
_NEW_ORDER_STAMPS: Final = typed_fields(NewOrder, datetime)


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


def require_lifecycle(lifecycle_state: LifecycleState | None, state: OrderState) -> None:
    """`ord_lifecycle` (21 Sec.3.3.4): a chart state comes only with the `order_state` value
    24 Sec.8.2 maps it to."""
    if lifecycle_state is not None and ORDER_STATE_OF.get(lifecycle_state) != state:
        raise ValueError("lifecycle_state is not the chart state of state (ord_lifecycle)")


def require_exchange_record(event: NewOrderEvent) -> None:
    """OM-R02: an event that puts an order in a state, `create`'s first one too, carries the
    exchange's message as its `payload` when the exchange reported it."""
    if event.source in EXCHANGE_SOURCES and not event.payload:
        raise ValueError("a step the exchange reported must carry its message (OM-R02)")


def require_no_fill(event: NewOrderEvent, to_state: OrderState | None = None) -> None:
    """A fill event, and `filled`, come with the execution that justifies them (OM-R02): only
    `ExecutionStore.commit_fill` writes them, so `transition` and `append` refuse them."""
    if event.kind in FILL_KINDS or to_state == "filled":
        raise ValueError("a fill is written by commit_fill, with its execution")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderTransition:
    """A write-ahead step (24 Sec.8.2 S8): `state` moves to `to_state` only while the row holds
    `from_state` (compare-and-set), and `event` is appended with both states, in one transaction.
    `reject_code`, `reject_message`, `lifecycle_state` (the chart state `to_state` persists),
    `exchange_order_id` (the exchange's id for the order, once B1 binds it, SR-E29-03) and the
    `terms` an accepted amend changed (`AMENDABLE`) are set when given; the row's CHECKs and
    `ux_orders_exch_id` still apply (a `qty` under `cum_exec_qty` is `ord_cum`'s). Built only from
    the columns' values, so every store refuses anything else alike, before any statement
    (OM-T04). The reject columns are the event's: a step into `rejected` names its event's
    `ret_code` and `ret_msg` as them, and no other step names any, so a fold of the order's events
    rebuilds them (OM-T03). E29-T04: `idempotency_state` when given; `bump_submit_attempts`, the
    send's step only (into `submitted`), counts `submit_attempts` up by one in SQL (`ord_attempts`
    refuses an eleventh); and `entry_stops` settles the entry's recorded stops in the step's own
    transaction (21 Sec.3.3.11's table), a step that leaves them waiting for the complete read
    naming none."""

    account_id: UUID
    order_id: UUID
    from_state: OrderState
    to_state: OrderState
    event: NewOrderEvent
    reject_code: str | None = None
    reject_message: str | None = None
    lifecycle_state: LifecycleState | None = None
    exchange_order_id: str | None = None
    terms: Mapping[str, Decimal] = field(default_factory=dict)
    idempotency_state: IdempotencyState | None = None
    bump_submit_attempts: bool = False
    entry_stops: EntryStopSettle | None = None

    def __post_init__(self) -> None:
        require_exchange_record(self.event)
        given = (self.from_state, self.to_state, self.event.kind, self.event.source)
        if any(value not in values for value, values in zip(given, _LITERALS, strict=True)):
            raise ValueError("a step's states, kind and source must be values of their columns")
        require_lifecycle(self.lifecycle_state, self.to_state)
        rejected = self.to_state == "rejected"
        said = (self.event.ret_code, self.event.ret_msg) if rejected else (None, None)
        if (self.reject_code, self.reject_message) != said:
            raise ValueError("a step's reject columns are its event's, on a step into rejected")
        if not set(self.terms) <= set(AMENDABLE):
            raise ValueError("a step changes only the terms an amend may change")
        for name, value in self.terms.items():
            require_money(name, value)
        if self.idempotency_state not in (None, *_IDEMPOTENCY_STATES):
            raise ValueError("idempotency_state must be a value of its column (ord_idem)")
        if self.bump_submit_attempts is not False and (
            self.bump_submit_attempts is not True or self.to_state != "submitted"
        ):
            raise ValueError("only the send's step, into submitted, counts an attempt")
        if self.entry_stops not in (None, *_ENTRY_STOP_SETTLES):
            raise ValueError("a step settles its entry's stops as answered or void")

    def changes(self) -> dict[str, object]:
        """The columns it sets, the exchange's text redacted like `ret_msg` (#845 decision 2)."""
        values: dict[str, object] = {"state": self.to_state}
        if self.lifecycle_state is not None:
            values["lifecycle_state"] = self.lifecycle_state
        if self.exchange_order_id is not None:
            values["exchange_order_id"] = self.exchange_order_id
        if self.idempotency_state is not None:
            values["idempotency_state"] = self.idempotency_state
        values.update(self.terms)
        if self.reject_code is not None:
            values["reject_code"] = redact_exchange_text(self.reject_code, max_chars=MAX_CODE_CHARS)
        if self.reject_message is not None:
            values["reject_message"] = redact_exchange_text(self.reject_message, message=True)
        return values


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
    lifecycle_state: LifecycleState | None
    provenance: OrderProvenance


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


@dataclass(frozen=True, slots=True)
class CommittedStep:
    """What a write-ahead step committed: the order row as it now stands, and its event."""

    order: OrderRow
    event: OrderEventRow


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


class StaleOrderState(OrderStoreError):
    """The compare-and-set missed (another writer moved the order first, or a fill's totals came
    from an older row): nothing was written. Names the order and state, never a payload."""

    def __init__(self, order_id: UUID, expected: OrderState) -> None:
        moved = f"order {order_id} moved on from {expected!r} or from the row a fill was built on"
        super().__init__(f"{moved}: nothing was written")
        self.order_id = order_id
        self.expected = expected


class FillRefused(OrderStoreError):
    """A fill its locked order refuses as hostile or malformed data (OM-T04), with nothing written:
    `cum_exec_qty` past `qty` (`above_qty`, INV-1), a paper flag unlike the order's
    (`paper_mismatch`, C-2.11's separate state), or `filled` reached without filling `qty`, or
    the reverse (`state_mismatch`). Names the order and the reason only; quantities are P1."""

    def __init__(self, order_id: UUID, reason: FillRefusal) -> None:
        super().__init__(f"order {order_id} refuses a fill ({reason}): nothing was written")
        self.order_id, self.reason = order_id, reason


@dataclass(frozen=True, slots=True)
class ScopedOrder:
    """`get_in_scope`'s order (24 Sec.8.4 "The exit routes", step 4) with what the exit routes
    judge it by: its trade group and the profile its leg was sized from, its creator (ruling Q6:
    its group's `created_by`, else its anchor's; None for an order no person created) and whether
    the scope may trade its account (ruling Q7: False for a view-only grant)."""

    order: OrderRow
    trade_group_id: UUID | None
    profile_id: UUID | None
    created_by: UUID | None
    can_trade: bool


@dataclass(frozen=True, slots=True)
class OutOfScope:
    """`get_in_scope`'s answer for an id outside the scope: the account of the order holding the
    id, None when none does, for the refusal's audit alone (ruling Q12), never for the answer,
    which is the same 404 either way (SR-E29-13)."""

    account_id: UUID | None


class AccountsOutOfScope(Exception):
    """`accounts_in_scope`: a requested account outside the scope, whichever (SR-E29-13). The
    caller's scope, never an outage, so no `OrderStoreError`, which the OMS reads as a store that
    did not serve (24 Sec.8.2 S7); `OrderRepository` answers it `AccountScopeDenied`."""


def settle_accounts(reach: Iterable[UUID], requested: Collection[UUID]) -> tuple[UUID, ...]:
    """`accounts_in_scope`'s answer from the accounts the scope reaches (among `requested`, when
    it names any): all of them for none requested; else `requested` once each, in its order, all
    or nothing."""
    reached = tuple(reach)
    if not requested:
        return reached
    wanted = tuple(dict.fromkeys(requested))
    if not set(wanted) <= set(reached):
        raise AccountsOutOfScope("an account the request names is outside its scope")
    return wanted


class OrderStore(Protocol):
    """Insert, the write-ahead step and account-scoped reads of `orders` (module docs)."""

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        """Insert the order and its first event (`seq` 0, `to_state` the order's state) in one
        statement, so one round trip in one transaction (#845 performance notes)."""
        ...

    async def transition(self, step: OrderTransition) -> CommittedStep:
        """Commit `step`, or raise with nothing written: `StaleOrderState` when the row no longer
        holds `step.from_state`, `OrderNotFoundError` outside the account, `ValueError` for a fill
        (`require_no_fill`)."""
        ...

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...

    async def get_by_exchange_order_id(
        self, account_id: UUID, exchange_order_id: str
    ) -> OrderRow | None:
        """The account's order bound to this exchange order id, in any state (`ux_orders_exch_id`,
        21 Sec.13.1 row 12): 24 Sec.8.12's pairing step 1. A final row's push is Sec.8.2's S6
        anomaly, so it is read, not hidden. The exact text; another account's order reads as
        missing, and an unbound order is never found. `ValueError` before any statement unless
        the id is text of 1 to `MAX_EXCHANGE_ORDER_ID_CHARS` characters."""
        ...

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        """The account's orders in `OPEN_STATES`, oldest first. Not paged: reconciliation needs
        every open order, and the exchange caps the active orders per symbol."""
        ...

    async def link_id_taken(self, order_link_id: str) -> bool:
        """Whether any row, of any account, in any state, holds the id (24 Sec.8.3 rule 5)."""
        ...

    async def get_in_scope(
        self, scope: AccountScope, order_id: UUID, *, environment: Environment
    ) -> ScopedOrder | OutOfScope:
        """The exit routes' order (E29-T04 slice 4) while `scope` reaches its account, in one
        statement holding the scope: an account of `environment`, not deleted; an Owner's while
        its user holds a live owner role, else one the user's live grant lets it view, unfrozen,
        among the scope's ids (C-12.4, SR-051). Else `OutOfScope`."""
        ...

    async def accounts_in_scope(
        self, scope: AccountScope, environment: Environment, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        """Cancel-all's accounts (E29-T04 slice 4): those of `environment` `scope` may trade, by
        `get_in_scope`'s predicate (a grant's trading, neither view-only nor frozen; an Owner's
        every live one): all of them, by id, when `requested` is empty, else `settle_accounts`'s
        answer, `AccountsOutOfScope` when one is outside, all or nothing (SR-E29-13)."""
        ...


class OrderEventStore(Protocol):
    """Append and account-scoped reads of `order_events`; a step's event is `transition`'s."""

    async def append(self, account_id: UUID, order_id: UUID, event: NewOrderEvent) -> OrderEventRow:
        """Append with the next `seq`, under a lock on the order row; no state transition
        (`from_state`, `to_state` NULL). `OrderNotFoundError` outside the account, `ValueError`
        for a fill's event (`require_no_fill`)."""
        ...

    async def list_for_order(
        self, account_id: UUID, order_id: UUID, *, after_seq: int = -1, limit: int = MAX_EVENT_PAGE
    ) -> tuple[OrderEventRow, ...]:
        """Events with `seq > after_seq`, in `seq` order; empty outside the account."""
        ...


class UnfinishedOrders(Protocol):
    """The OMS runtime's startup hydration read (E29-T04 #913, 20 Sec.6.2), kept apart from
    `OrderStore`'s account-scoped surface (module docstring)."""

    async def list_unfinished(
        self, environment: Environment, *, limit: int
    ) -> tuple[OrderRow, ...]:
        """The orders in `UNFINISHED_STATES` of every account of `environment`, a disabled or
        soft-deleted one's too, oldest first, at most `limit` (`require_limit`, before any read)."""
        ...

    async def environment_accounts(self, environment: Environment) -> tuple[UUID, ...]:
        """The ids of every account of `environment`, a disabled or soft-deleted one's too: the
        startup sweep's account set (20 Sec.6.2 step 2)."""
        ...
