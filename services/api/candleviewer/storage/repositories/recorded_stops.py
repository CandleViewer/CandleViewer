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

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.storage.repositories.orders import (
    ORDER_STATE_OF,
    OrderSide,
    OrderState,
    OrderStoreError,
    TpslMode,
    check_fields,
    typed_fields,
)

__all__ = [
    "EVERY_ACCOUNT", "MAX_MARKER_CHARS", "REFUSED_BY", "REFUSED_ENTRY", "SWEEP_REASON",
    "UNSENT_ENTRY", "UX_RS_IN_FLIGHT", "UX_RS_IN_FORCE", "NewRecordedStop", "RecordedStopRow",
    "RecordedStopStore", "SettleWriteAhead", "StaleRecordedStop", "StopEnd", "StopKind",
    "StopOutcome", "StopSource", "StopStatus", "SweepScope", "SweepWriteAhead", "SweptStop",
    "check_request",
]  # fmt: skip

StopKind = Literal["stop_loss", "take_profit"]
StopSource = Literal["entry_attach", "trading_stop", "restore"]
StopStatus = Literal["pending", "in_force", "replaced", "ended", "void"]
#: How an `ended` row ended (24 Sec.8.8 rule 6, 21 Sec.3.3.11): `in_force`, after a read showed its
#: stop, or `answered_unread`, a request the exchange accepted that no read showed before its
#: position closed (no `in_force_at`, which `rs_times` admits only with `answered_at` set).
StopEnd = Literal["in_force", "answered_unread"]
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
#: The startup sweep's whole scope (`void_orphans`, 21 Sec.3.3.11) is an entry never placed: one
#: never sent, or one the create's own answer refused. `UNSENT_ENTRY` holds the `orders` columns,
#: and the values (a set: any of them), that prove the first: the send's own step marks the create
#: in flight and counts its attempt, committed, before any create can leave (24 Sec.8.4; B1 arms
#: the place only after that write), so an order still `pending_submit`, or killed before its send
#: (`abandon`), its create `unsent`, no attempt counted and nothing filled had no exchange
#: interaction (the orchestrator's rulings of 14:26Z).
UNSENT_ENTRY: Final[Mapping[str, object]] = MappingProxyType(
    {
        "state": frozenset({"pending_submit", "killed"}),
        "idempotency_state": "unsent",
        "submit_attempts": 0,
        "cum_exec_qty": Decimal(0),
    }
)
#: The second: `rejected` with nothing filled, and its own `order_events` row into `rejected`
#: (`REFUSED_BY`, the persisted states) came out of `submitting`, which only the create's answer
#: leaves for `rejected`. A rejection out of `unknown` or `held` (reconciliation's, the operator's)
#: is no such proof. No other order's rows are swept: its own steps settle them, voiding them only
#: for an entry never sent or on an end the exchange confirmed unfilled, or leave them waiting for
#: the complete read (24 Sec.8.8 rule 6), the rows of an order killed after its send and of one
#: that ended out of `unknown` among them, so the sweep never voids a row blind (C-2.6).
REFUSED_ENTRY: Final[Mapping[str, object]] = MappingProxyType(
    {"state": "rejected", "cum_exec_qty": Decimal(0)}
)
REFUSED_BY: Final[tuple[OrderState, OrderState]] = (
    ORDER_STATE_OF["submitting"],
    ORDER_STATE_OF["rejected"],
)
#: The audit reason of a row the startup sweep voids (`sl.modified`, or `tp.modified` for a
#: take-profit side, 21 Sec.3.3.11): its entry was never placed. The sweep's write-ahead hook
#: records it.
SWEEP_REASON: Final = "unplaced_entry_swept"


class SweepScope(Enum):
    """The startup sweep's scope when it is not one account. Named, so that an account a caller
    forgot (`None`) is refused and never read as every account (CR-2A-07)."""

    EVERY_ACCOUNT = "every_account"


#: `void_orphans` over every account: the one call slice 3's startup wiring makes.
EVERY_ACCOUNT: Final = SweepScope.EVERY_ACCOUNT


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


def check_request(stops: Sequence[NewRecordedStop]) -> None:
    """`ValueError`, before any statement, unless `stops` are the rows of one stop request (21
    Sec.3.3.11, CR-2A-03): its stop-loss side exactly once, as every request records it and
    `ux_rs_in_flight` admits one request in flight per position through that row alone, and its
    take-profit at most once; one position (account, symbol, `position_idx` and side); one source
    and one order (an entry's, or none). Names no value (21 Sec.12)."""
    if not stops:
        raise ValueError("a stop request records at least one row")
    kinds = [stop.kind for stop in stops]
    if kinds.count("stop_loss") != 1 or len(set(kinds)) != len(kinds):
        raise ValueError("a stop request records its stop-loss side once, and each side once")
    first = stops[0]
    place = (first.exchange_account_id, first.symbol, first.position_idx, first.position_side)
    for stop in stops[1:]:
        if (stop.exchange_account_id, stop.symbol, stop.position_idx, stop.position_side) != place:
            raise ValueError("a stop request protects one position")
        if (stop.source, stop.order_id) != (first.source, first.order_id):
            raise ValueError("a stop request has one source and one order")


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

    @property
    def end(self) -> StopEnd | None:
        """How the row ended, None unless it is `ended`. The two ends never read alike (the
        orchestrator's ruling on #4010's CR-G6-R4-05 (f)): slice 3's complete read and
        reconciliation never take an answered, unread end for one a read confirmed in force."""
        if self.status != "ended":
            return None
        return "in_force" if self.in_force_at is not None else "answered_unread"


@dataclass(frozen=True, slots=True)
class SweptStop:
    """A row `void_orphans` voided, by its ids and kind only: its audit record (`sl.modified`, or
    `tp.modified` for a take-profit side, reason `unplaced_entry_swept`) names nothing else."""

    id: UUID
    exchange_account_id: UUID
    order_id: UUID
    kind: StopKind


#: Awaited once in the sweep's transaction, before its commit, with the rows it voided: the
#: caller's write-ahead audit (C-2.9). A hook that raises, or outlasts the store's audit bound
#: (`WriteAheadTimeout`), leaves every row as it was.
SweepWriteAhead = Callable[[tuple[SweptStop, ...]], Awaitable[None]]
#: Awaited once in a settle's transaction, after its update and before its commit, with the rows
#: as settled: the writer's write-ahead audit (C-2.9, SEC-2A-05), as for a row a refusal or a
#: complete read voids (`sl.modified`, or `tp.modified`, 21 Sec.3.3.11). A hook that raises, or
#: outlasts the store's audit bound (`WriteAheadTimeout`), leaves every row as it was.
SettleWriteAhead = Callable[[tuple[RecordedStopRow, ...]], Awaitable[None]]


class StaleRecordedStop(OrderStoreError):
    """A settle met a row that is not in flight any more (another writer answered it first) or not
    in the account: nothing was written. Names no value."""

    def __init__(self) -> None:
        super().__init__("a recorded stop is no longer in flight: nothing was written")


class RecordedStopStore(Protocol):
    """The recorded stops' writes and reads; no route reaches it (C-12.4)."""

    async def insert(self, stops: Sequence[NewRecordedStop]) -> tuple[RecordedStopRow, ...]:
        """Insert one request's rows in one transaction, all or none, and return them as stored.
        `ValueError` before any statement unless they are one request's (`check_request`);
        `OrderConstraintError(UX_RS_IN_FLIGHT)` when a request is in flight for the position."""
        ...

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
        write_ahead: SettleWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        """Answer one request's rows together (21 Sec.3.3.11): each must be the account's and in
        flight, else `StaleRecordedStop` with nothing written. `write_ahead`, when given, is
        awaited with the settled rows before the commit, bounded; `WriteAheadTimeout` when it
        outlasts the bound, with nothing written. A void (`refused`, `not_shown`) needs it: with
        none, `ValueError` before any statement (C-2.9), here as in the M14 facade. Returns them
        as stored."""
        ...

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        """An entry's attach rows, oldest first; empty outside the account."""
        ...

    async def void_orphans(
        self, scope: UUID | SweepScope, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        """The startup sweep (R10): every pending entry-attach row, of the `scope` account or, for
        `EVERY_ACCOUNT`, of every account, whose order is of the row's account and was never placed
        (`UNSENT_ENTRY`, or `REFUSED_ENTRY` with its `REFUSED_BY` event), becomes `void`
        (`closed_at` = `at`), the hook awaited before the commit (`SWEEP_REASON`). A row of any
        other order is left as it is: an order's killed after its send, one's that ended out of
        `unknown` and one's whose end the exchange did not confirm unfilled wait for the complete
        read, never voided blind. Only at startup, before the order machines hydrate and before
        order entry opens (slice 3's wiring): a `pending_submit` order is an orphan only while no
        request can still send it, and a sweep after that could void an entry about to be sent."""
        ...
