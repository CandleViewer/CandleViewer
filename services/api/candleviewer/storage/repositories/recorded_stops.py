"""Driver-free port for the recorded stops (E29-T04 #913; 21-database-schema.md Sec.3.3.11,
revision `0043_order_submission`, M10).

Stdlib only, with the sibling port `orders`, so M14 (`oms`) types against it with no storage
driver (ADR-0003); `recorded_stops_sqlalchemy.py` is the Postgres implementation, and an entry's
attach rows are written with the order by the first persist (`submissions.py`).

A row is one stop the OMS requests for a position (SR-E29-06, 24 Sec.8.8 rule 6), written ahead of
its request, `pending` and in flight (`answered_at` NULL). `ux_rs_in_flight` admits one request in
flight per position (account, symbol, `position_idx`), keyed on its stop-loss row; the answer sets
`answered_at`, and a refusal makes the row `void`. A row never leaves the table, and its request's
values never change (`trg_rs_guard`). Every read and update takes the exchange account and filters
on it (C-12.4), so another account's row reads as missing; the one write that does not is the
insert, which writes the account each row names.

Every value a writer gives is refused, before any statement, by the rule the table would refuse it
with (`rs_px`, `rs_size`, `rs_trail`, `rs_entry`, `rs_restore`, `rs_marker`, the money columns'
numeric(38,18)), and no error names a value: the prices and sizes are class P1 (21 Sec.12).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.storage.repositories.orders import (
    OrderSide,
    OrderState,
    OrderStoreError,
    TpslMode,
    check_fields,
    typed_fields,
)

__all__ = [
    "MAX_MARKER_CHARS", "ORPHANING_STATES", "UX_RS_IN_FLIGHT", "UX_RS_IN_FORCE",
    "NewRecordedStop", "RecordedStopRow", "RecordedStopStore", "StaleRecordedStop", "StopKind",
    "StopOutcome", "StopSource", "StopStatus", "SweepWriteAhead", "SweptStop",
]  # fmt: skip

StopKind = Literal["stop_loss", "take_profit"]
StopSource = Literal["entry_attach", "trading_stop", "restore"]
StopStatus = Literal["pending", "in_force", "replaced", "ended", "void"]
#: How `settle` answers a request in flight: the exchange answered it (`answered`: the row stays
#: pending until a read shows its stop), refused it (`refused`), or a complete read after its
#: bound showed neither its stop nor an order or entry that carries it (`not_shown`, 21
#: Sec.3.3.11). Both of the last two make the row `void`.
StopOutcome = Literal["answered", "refused", "not_shown"]
#: One request in flight per position (21 Sec.3.3.11): a second writer's insert is refused.
UX_RS_IN_FLIGHT: Final = "ux_rs_in_flight"
#: One row in force per position and kind.
UX_RS_IN_FORCE: Final = "ux_rs_in_force"
#: `rs_marker`: the position's instance marker, 1 to 64 characters (`[O-4]`, E29-K01).
MAX_MARKER_CHARS: Final = 64
#: The order states in which an entry's pending stop rows are orphans once its order holds no
#: fill (`void_orphans`): never sent (`pending_submit`, which no live request owns after a
#: restart), or ended unfilled, so its attached stop never reached a position.
ORPHANING_STATES: Final[frozenset[OrderState]] = frozenset(
    {"pending_submit", "rejected", "held", "killed", "cancelled", "expired"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class NewRecordedStop:
    """A `recorded_stops` row to insert ahead of its request: the request's values, which never
    change. `audit_record_id` is the `record_id` of the request's write-ahead audit record, which
    the writer assigns (21 Sec.3.3.11 "Audit"); `actor_user_id` is `None` for a system writer.
    `position_marker` is the instance marker of the position a trading-stop writer read, when it
    read one; an entry's attach has no position yet."""

    id: UUID
    exchange_account_id: UUID
    symbol: str
    position_idx: Literal[0, 1, 2]
    position_side: OrderSide
    kind: StopKind
    source: StopSource
    order_id: UUID | None
    tpsl_mode: TpslMode
    trigger_price: Decimal
    size: Decimal | None
    trailing_distance: Decimal | None = None
    trailing_active_price: Decimal | None = None
    audit_record_id: UUID
    actor_user_id: UUID | None
    position_marker: str | None = None

    def __post_init__(self) -> None:
        check_fields(self, _STOP_MONEY, ())
        if not self.trigger_price > 0:
            raise ValueError("trigger_price must be above zero (rs_px)")
        if self.tpsl_mode == "Partial":
            sized = self.size is not None and self.size > 0
        else:
            sized = self.size is None
        if not sized:
            raise ValueError("a Partial side carries a size above zero, a Full one none (rs_size)")
        distance, active = self.trailing_distance, self.trailing_active_price
        if (distance is None) != (active is None):
            raise ValueError("a trail has its distance and its activation price (rs_trail)")
        if distance is not None and active is not None:
            if not (self.kind == "stop_loss" and distance > 0 and active > 0):
                raise ValueError("a trail is a stop-loss's, both numbers above zero (rs_trail)")
        if (self.source == "entry_attach") != (self.order_id is not None):
            raise ValueError("an entry's attach, and only one, names its order (rs_entry)")
        if self.source == "restore" and self.kind != "stop_loss":
            raise ValueError("a restore records only the stop-loss (rs_restore)")
        marker = self.position_marker
        if marker is not None and not 1 <= len(marker) <= MAX_MARKER_CHARS:
            raise ValueError(f"position_marker must be 1 to {MAX_MARKER_CHARS} chars (rs_marker)")


_STOP_MONEY: Final = dict.fromkeys(typed_fields(NewRecordedStop, Decimal), (38, 18))


@dataclass(frozen=True, slots=True)
class RecordedStopRow:
    """One `recorded_stops` row, every column in table order (pinned to the table by a test)."""

    id: UUID
    exchange_account_id: UUID
    symbol: str
    position_idx: int
    position_side: OrderSide
    kind: StopKind
    source: StopSource
    order_id: UUID | None
    tpsl_mode: TpslMode
    trigger_price: Decimal
    size: Decimal | None
    trailing_distance: Decimal | None
    trailing_active_price: Decimal | None
    exchange_order_id: str | None
    status: StopStatus
    audit_record_id: UUID
    actor_user_id: UUID | None
    created_at: datetime
    answered_at: datetime | None
    in_force_at: datetime | None
    closed_at: datetime | None
    released_at: datetime | None
    position_marker: str | None


@dataclass(frozen=True, slots=True)
class SweptStop:
    """A row `void_orphans` voided, by its ids and kind only: its audit record (`sl.modified`, or
    `tp.modified` for a take-profit side, reason `orphan_swept`) names nothing else."""

    id: UUID
    exchange_account_id: UUID
    order_id: UUID
    kind: StopKind


#: Awaited once in the sweep's transaction, before its commit, with the rows it voided: the
#: caller's write-ahead audit (C-2.9). A hook that raises, or outlasts the store's audit bound
#: (`WriteAheadTimeout`), leaves every row as it was.
SweepWriteAhead = Callable[[tuple[SweptStop, ...]], Awaitable[None]]


class StaleRecordedStop(OrderStoreError):
    """A settle met a row that is not in flight any more (another writer answered it first) or not
    in the account: nothing was written. Names no value."""

    def __init__(self) -> None:
        super().__init__("a recorded stop is no longer in flight: nothing was written")


class RecordedStopStore(Protocol):
    """The recorded stops' writes and reads; no route reaches it (C-12.4)."""

    async def insert(self, stops: Sequence[NewRecordedStop]) -> tuple[RecordedStopRow, ...]:
        """Insert one request's rows in one transaction, all or none, and return them as stored.
        `OrderConstraintError(UX_RS_IN_FLIGHT)` when a request is in flight for the position."""
        ...

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
    ) -> tuple[RecordedStopRow, ...]:
        """Answer one request's rows together (21 Sec.3.3.11): each must be the account's and in
        flight, else `StaleRecordedStop` with nothing written. Returns them as stored."""
        ...

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        """An entry's attach rows, oldest first; empty outside the account."""
        ...

    async def void_orphans(
        self, account_id: UUID | None, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        """The startup sweep (R10): every pending entry-attach row, of `account_id` or of every
        account, whose order holds no fill and is in `ORPHANING_STATES`, or is not an order of the
        row's account, becomes `void` (`closed_at` = `at`), the hook awaited before the commit.
        Only at startup, before the order machines hydrate and order entry opens: a
        `pending_submit` order is an orphan only while no request can still send it."""
        ...
