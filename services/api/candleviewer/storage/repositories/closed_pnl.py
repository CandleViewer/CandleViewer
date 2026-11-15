"""Driver-free closed-PnL record store (E29-S06 #981 slice 2; 21 Sec.3.3.13, 24 Sec.8.13).

One row per venue closed-PnL record of a closing order, named by its uuid5 (`record_id`, or
`orderless_record_id` under the empty-orderId rule), so the item the stored closing fills compose
and the item the venue's record settles are one row. The composition writes `ComposedRecord`, its
`trade_group_id` included, which only it writes; a venue read writes `VenueRecord`, settling the
row once and replacing the venue's columns until the record is final (`settle_outcome`);
`finalize` freezes them. A record refuses, before any statement and naming the rule, never a
value, what the table would: an order id of 1 to 64 characters, `long` or `short`, a
`position_idx` of 0, 1 or 2, a `qty` above 0, money numeric(38,18) holds exactly (`leverage`
numeric(10,2)); every time is aware. The reads are 21 Sec.13.1 rows 55 to 59, 61 and 62, each
bounded by its caller's limit or the names it is given, and the totals by their window, which a
query must name (`TotalsUnbounded`) (C-2.18). `closed_pnl_sqlalchemy.py` is the Postgres side; the
route is E29-S06's later slice.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Literal, Protocol, get_args
from uuid import UUID, uuid5

from candleviewer.storage.repositories.executions import ExecType
from candleviewer.storage.repositories.oms_reads import Keyset
from candleviewer.storage.repositories.orders import (
    OrderSide,
    OrderState,
    check_fields,
    require_aware,
    require_exchange_order_id,
    typed_fields,
)

#: 22 `ClosedPnl`'s `x-cv-uuid5-namespace`.
CLOSED_PNL_NAMESPACE: Final = UUID("3697d71d-71d6-4c1f-b0fc-9c25507038b1")
#: The closed position's side (`cpr_side`, 22 `JournalSide`): a `sell` closes a `long`.
ClosedSide = Literal["long", "short"]
#: What a venue read did to its row: created it settled, settled it, replaced its venue's columns,
#: nothing as the row holds the read, or nothing as the row is final and the read differs, which
#: its caller logs at WARNING (24 Sec.8.13).
SettleOutcome = Literal["inserted", "settled", "replaced", "unchanged", "frozen"]
CLOSED_SIDES: Final[frozenset[str]] = frozenset(get_args(ClosedSide))
#: The venue's columns: a read replaces them until `final_at`, then `trg_cpr_guard` freezes them.
VENUE_COLUMNS: Final = (
    "qty", "avg_entry_price", "avg_exit_price", "leverage", "closed_pnl", "closed_at",
    "venue_created_at",
)  # fmt: skip
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def record_id(account_id: UUID, exchange_order_id: str) -> UUID:
    return uuid5(CLOSED_PNL_NAMESPACE, f"{account_id}:order:{exchange_order_id}")


def orderless_record_id(
    account_id: UUID, symbol: str, side: ClosedSide, created_at: datetime
) -> UUID:
    """The empty-orderId rule's id: the item's side and the venue's `createdTime`, in ms."""
    created_ms = (created_at - _EPOCH) // timedelta(milliseconds=1)
    return uuid5(CLOSED_PNL_NAMESPACE, f"{account_id}:record:{symbol}:{side}:{created_ms}")


def _check(record: ComposedRecord | VenueRecord, money: dict[str, tuple[int, int]]) -> None:
    check_fields(record, money, tuple(n for n in _STAMPS if hasattr(record, n)))
    if record.side not in CLOSED_SIDES:
        raise ValueError("cpr_side: the side is long or short")
    if record.qty is not None and record.qty <= 0:
        raise ValueError("cpr_qty: qty is above 0")


@dataclass(frozen=True, slots=True, kw_only=True)
class ComposedRecord:
    """The composition's write: the local figures, None when not composed, its position's trade
    group (24 Sec.8.13: the one its opening fills name, else None), which it may rewrite at any
    stage, and the provisional `qty`, prices and `closed_at`, which a settled row keeps as the
    venue's. It names its order."""

    exchange_account_id: UUID
    exchange_order_id: str
    symbol: str
    side: ClosedSide
    closed_at: datetime
    position_idx: Literal[0, 1, 2] | None = None
    trade_group_id: UUID | None = None
    qty: Decimal | None = None
    avg_entry_price: Decimal | None = None
    avg_exit_price: Decimal | None = None
    gross_pnl: Decimal | None = None
    fee_pnl: Decimal | None = None
    funding_pnl: Decimal | None = None
    opened_at: datetime | None = None

    def __post_init__(self) -> None:
        require_exchange_order_id(self.exchange_order_id)
        _check(self, dict.fromkeys(typed_fields(ComposedRecord, Decimal), (38, 18)))
        if self.position_idx not in (None, 0, 1, 2):
            raise ValueError("cpr_posidx: position_idx is 0, 1 or 2")

    @property
    def id(self) -> UUID:
        return record_id(self.exchange_account_id, self.exchange_order_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class VenueRecord:
    """A venue record as a read gives it, several under one `orderId` taken as one (24 Sec.8.13);
    `exchange_order_id` None is the empty-orderId rule's."""

    exchange_account_id: UUID
    exchange_order_id: str | None
    symbol: str
    side: ClosedSide
    qty: Decimal
    avg_entry_price: Decimal
    avg_exit_price: Decimal
    leverage: Decimal
    closed_pnl: Decimal
    closed_at: datetime
    venue_created_at: datetime

    def __post_init__(self) -> None:
        if self.exchange_order_id is not None:
            require_exchange_order_id(self.exchange_order_id)
        money = dict.fromkeys(typed_fields(VenueRecord, Decimal), (38, 18))
        _check(self, money | {"leverage": (10, 2)})

    @property
    def id(self) -> UUID:
        if self.exchange_order_id is None:
            args = (self.exchange_account_id, self.symbol, self.side, self.venue_created_at)
            return orderless_record_id(*args)
        return record_id(self.exchange_account_id, self.exchange_order_id)


_STAMPS: Final = ("closed_at", "opened_at", "venue_created_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosedPnlRecordRow:
    """One `closed_pnl_records` row, every column in table order."""

    id: UUID
    exchange_account_id: UUID
    exchange_order_id: str | None
    symbol: str
    side: ClosedSide
    position_idx: int | None
    trade_group_id: UUID | None
    qty: Decimal | None
    avg_entry_price: Decimal | None
    avg_exit_price: Decimal | None
    leverage: Decimal | None
    closed_pnl: Decimal | None
    gross_pnl: Decimal | None
    fee_pnl: Decimal | None
    funding_pnl: Decimal | None
    opened_at: datetime | None
    closed_at: datetime
    venue_created_at: datetime | None
    settled_at: datetime | None
    final_at: datetime | None
    divergent: bool
    audited_local_net: Decimal | None
    audited_closed_pnl: Decimal | None
    updated_at: datetime


def settle_outcome(held: ClosedPnlRecordRow | None, record: VenueRecord) -> SettleOutcome:
    """What a venue read does to the row it names, as the account's lock holds it."""
    if held is None:
        return "inserted"
    same = all(getattr(held, name) == getattr(record, name) for name in VENUE_COLUMNS)
    if held.final_at is not None:
        return "unchanged" if same else "frozen"
    if held.settled_at is None:
        return "settled"
    return "unchanged" if same else "replaced"


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosedPnlQuery:
    """22 `listClosedPnl`'s filters over the accounts its caller settled: `symbols` are
    alternatives, and so are `trade_groups`, matched on the stored `trade_group_id`, which a NULL
    never matches (row 59); `side` narrows; `since` is inclusive and `until` exclusive, on
    `closed_at`, and the totals need both (`require_window`); `oldest_first` is a window read's
    order, newest first the other's (22 "Order")."""

    accounts: tuple[UUID, ...]
    symbols: tuple[str, ...] = ()
    trade_groups: tuple[UUID, ...] = ()
    side: ClosedSide | None = None
    since: datetime | None = None
    until: datetime | None = None
    oldest_first: bool = True

    def __post_init__(self) -> None:
        if not self.accounts or self.side not in (None, *CLOSED_SIDES):
            raise ValueError("a read names its accounts, and a side is long or short")
        for name in ("since", "until"):
            if (value := getattr(self, name)) is not None:
                require_aware(name, value)


class TotalsUnbounded(ValueError):
    """The totals of a query without both `since` and `until`, refused before any statement: a
    sum over the accounts' whole history is no read its caller bounds (C-2.18), and 22 serves
    totals only for a window. Names no value."""


def require_window(query: ClosedPnlQuery) -> None:
    """`TotalsUnbounded` unless the query names its window, `since` and `until` both."""
    if query.since is None or query.until is None:
        raise TotalsUnbounded("the totals read a window: since and until are both named")


@dataclass(frozen=True, slots=True)
class ListedClosedPnl:
    """A served item and its `net_pnl`, computed in SQL as the totals sum it: None for a
    provisional item without a `gross_pnl`, served all the same (24 Sec.8.13)."""

    row: ClosedPnlRecordRow
    net_pnl: Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountTotals:
    """22 `ClosedPnlAccountTotals`."""

    exchange_account_id: UUID
    count: int
    net_pnl: Decimal
    provisional: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosedPnlTotals:
    """22 `ClosedPnlTotals`: the query's items across all pages, every one counted and `net_pnl`
    the sum of those that have one, `by_account` in account order."""

    count: int
    net_pnl: Decimal
    provisional: bool
    by_account: tuple[AccountTotals, ...]


@dataclass(frozen=True, slots=True)
class PendingRecord:
    """A record the settle poll reads again (row 56), with its closing order's row."""

    row: ClosedPnlRecordRow
    order_id: UUID
    order_state: OrderState


@dataclass(frozen=True, slots=True)
class FillKey:
    """Where a walk's read of fills starts: strictly after `at`, a confirmed flat's venue time,
    which comes after every fill dated at or before it; or after the fill (`at`, `exec_id`)."""

    at: datetime
    exec_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkFill:
    """A fill the walk reads (row 58) with its order row's `position_idx` and venue order id, both
    None when it has no order row, and the trade group its order row's leg names, through a leg
    of the fill's own account alone (None: no row, no leg, or another account's)."""

    exec_id: str
    exec_ts: datetime
    order_id: UUID | None
    side: OrderSide
    exec_type: ExecType
    exec_qty: Decimal
    exec_price: Decimal
    exec_fee: Decimal
    closed_pnl: Decimal | None
    closed_size: Decimal | None
    order_position_idx: int | None
    order_exchange_id: str | None
    order_group_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderAnchor:
    """An order row the composition reads (row 61), with its stored trade fills' first and last
    times and the last of those stating a `closedSize` above 0 (all None with none stored), its
    key's last confirmed flat before the first, where its walk starts (None: no start), and
    whether its record is stored (`held`)."""

    order_id: UUID
    exchange_order_id: str | None
    symbol: str
    side: OrderSide
    position_idx: int
    state: OrderState
    first_fill: datetime | None
    last_fill: datetime | None
    last_close: datetime | None
    start: datetime | None
    held: bool


class ClosedPnlStore(Protocol):
    """Account-scoped writes and reads of `closed_pnl_records` (C-12.4): each call is one
    transaction, capped by the OMS statement timeout, which its caller bounds (C-2.18)."""

    async def compose(self, record: ComposedRecord) -> ClosedPnlRecordRow: ...
    async def settle(self, record: VenueRecord) -> SettleOutcome: ...
    async def finalize(self, account_id: UUID, record_id: UUID) -> bool: ...
    async def get(self, account_id: UUID, record_id: UUID) -> ClosedPnlRecordRow | None: ...
    async def page(
        self, query: ClosedPnlQuery, after: Keyset | None, limit: int
    ) -> tuple[ListedClosedPnl, ...]: ...
    async def totals(self, query: ClosedPnlQuery) -> ClosedPnlTotals:
        """The query's items across all pages, in the window it must name: without `since` and
        `until` both, `TotalsUnbounded` before any statement (`require_window`)."""

    async def pending(
        self, account_id: UUID, reach: datetime, limit: int
    ) -> tuple[PendingRecord, ...]: ...
    async def walk_flats(
        self, account_id: UUID, symbol: str, position_idx: int, before: datetime, limit: int
    ) -> tuple[datetime, ...]:
        """The key's confirmed flats from the last one before `before`, oldest first, each venue
        time once: the copies of one reading the stream and each reconciliation store are one."""

    async def walk_fills(
        self, account_id: UUID, symbol: str, position_idx: int, after: FillKey, limit: int
    ) -> tuple[WalkFill, ...]: ...
    async def anchors(
        self, account_id: UUID, orders: Collection[UUID], exchange_order_ids: Collection[str]
    ) -> tuple[OrderAnchor, ...]:
        """The account's order rows named by id or by venue id, each once, by id."""

    async def hedged(self, account_id: UUID, symbol: str) -> bool:
        """Whether the account holds a position of the symbol at `position_idx` 1 or 2."""
