"""Driver-free port for the recorded stops (E29-T04 #913; 21-database-schema.md Sec.3.3.11,
revision `0043_order_submission`, M10).

Stdlib only, with the sibling port `orders`, so M14 (`oms`) types against it with no storage
driver (ADR-0003); `recorded_stops_sqlalchemy.py` is the Postgres implementation, and an entry's
attach rows are written with the order by the first persist (`submissions.py`).

A row is one stop the OMS requests for a position (SR-E29-06, 24 Sec.8.8 rule 6), written ahead of
its request, `pending` and in flight (`answered_at` NULL), with the writer's audit of the request
in the insert's transaction (`InsertWriteAhead`). `ux_rs_in_flight` admits one request in flight
per position (account, symbol, `position_idx`), keyed on its stop-loss row; the answer sets
`answered_at`, and a refusal makes the row `void`. A row left unanswered past its request's bound,
and an entry's row waiting for the complete read (`WAITING_ENTRY`), hold their key until that read:
`waiting_for_key` lists them, and no other stop request for the key leaves while it lists any (21
Sec.3.3.11). A row in flight inside its bound is not listed: a second request meets it at the
insert (`ux_rs_in_flight`) and retries (the orchestrator's Q2 ruling). A row never leaves the table,
and its request's values never change (`trg_rs_guard`). Every read and update takes the exchange
account and filters on it (C-12.4), so another account's row reads as missing; the one write that
does not is the insert, which writes the account each row names.

Every value a writer gives is refused, before any statement, by the rule the table would refuse it
with (`rs_px`, `rs_size`, `rs_trail`, `rs_entry`, `rs_restore`, `rs_marker`, the money columns'
numeric(38,18)), and no error names a value: the prices and sizes are class P1 (21 Sec.12).
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    require_aware,
    typed_fields,
)

__all__ = [
    "EVERY_ACCOUNT", "LIVE_STOP_STATUSES", "MAX_MARKER_CHARS", "REFUSED_BY", "REFUSED_ENTRY",
    "STOP_AUDIT_TIMEOUT_S", "SWEEP_REASON", "UNSENT_ENTRY", "UX_RS_IN_FLIGHT", "UX_RS_IN_FORCE",
    "WAITING_ENTRY",
    "FillPosition", "InForce", "InForceWriteAhead", "InsertWriteAhead", "NewRecordedStop",
    "RecordedStopNotBindable", "RecordedStopRow",
    "RecordedStopStore", "ReleaseWriteAhead", "ResolveOutcome", "ResolveWriteAhead",
    "SettleWriteAhead",
    "StaleRecordedStop", "StopEnd", "StopKind", "StopOutcome", "StopSource", "StopStatus",
    "SweepScope", "SweepWriteAhead", "SweptStop", "check_in_force", "check_request",
    "check_resolve", "request_cutoff",
]  # fmt: skip

StopKind = Literal["stop_loss", "take_profit"]
StopSource = Literal["entry_attach", "trading_stop", "restore"]
StopStatus = Literal["pending", "in_force", "replaced", "ended", "void"]
#: The live statuses: the `ix_rs_live` predicate (a unit test pins it), what `live_for_key` reads
#: (21 Sec.13.1 row 45). Driver-free, so the in-memory store can use it.
LIVE_STOP_STATUSES: Final = frozenset[StopStatus]({"pending", "in_force"})
#: How an `ended` row ended (24 Sec.8.8 rule 6, 21 Sec.3.3.11): `in_force`, after a read showed its
#: stop, or `answered_unread`, a request the exchange accepted that no read showed before its
#: position closed (no `in_force_at`, which `rs_times` admits only with `answered_at` set).
StopEnd = Literal["in_force", "answered_unread"]
#: How `settle` answers a request in flight: the exchange answered it (`answered`: the row stays
#: pending until a read shows its stop), refused it (`refused`), or a complete read after its
#: bound showed neither its stop nor an order or entry that carries it (`not_shown`, 21
#: Sec.3.3.11). Both of the last two make the row `void`.
StopOutcome = Literal["answered", "refused", "not_shown"]
#: How `resolve` settles pending rows: `answered` stamps a NULL `answered_at`, keeping them pending;
#: `replaced` (a row of the key and kind already in force) stamps it too; the others void them,
#: each its audit's reason (`entry_filled_stop_absent`: the Q1 ruling).
ResolveOutcome = Literal["answered", "replaced", "in_flight_resolved", "entry_filled_stop_absent"]
#: Whether the position was open or flat when its filled entry's side was voided (CR-S3H0-08), or
#: when an unseen entry's rows were voided on a position with no stop (the 06:38Z ruling).
FillPosition = Literal["open", "flat"]
#: The recorded stops' write-ahead audit bound (s), every store's default (the SQL store's and the
#: fakes'), driver-free so the OMS may read it (`stop_resolution.STORE_TIMEOUT_S` outlasts it); a
#: unit test pins it to the drivers' `WRITE_AHEAD_TIMEOUT_S`.
STOP_AUDIT_TIMEOUT_S: Final = 5.0
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
#: (`REFUSED_BY`, the persisted states) came out of `submitting`, which leaves for `rejected` only
#: on an answer that the entry was never placed: the create's own refusal, or the command port's
#: `EXPIRED_UNSENT` for a create a restart resumed that no lookup found within the venue's 24 h
#: history, so it never landed (24 Sec.8.3 rule 6, [LANE-26]). Past that history a miss proves
#: nothing, and the port answers `unknown` instead, never `rejected` (SEC-2B1-02). A rejection
#: out of `unknown` or `held` (reconciliation's, the operator's) is no such proof. No other order's
#: rows are swept: its own steps settle them, voiding them only for an entry never sent or on an
#: end the exchange confirmed unfilled, or leave them waiting for the complete read (24 Sec.8.8
#: rule 6), the rows of an order killed after its send and of one that ended out of `unknown`
#: among them, so the sweep never voids a row blind (C-2.6).
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
#: The `orders` columns, and the values, of an entry whose pending attach rows, answered or not,
#: wait for the complete read (21 Sec.3.3.11's table): it ended (`killed`, `expired`, `cancelled`,
#: `rejected`) or is `held` with nothing filled, on a step that could not tell whether it filled.
#: The steps that can tell void the rows instead (an end the exchange confirmed unfilled, a KILL
#: before the send), and a fill makes them its position's stop.
WAITING_ENTRY: Final[Mapping[str, object]] = MappingProxyType(
    {
        "state": frozenset(
            ORDER_STATE_OF[state]
            for state in ("killed", "expired", "cancelled", "rejected", "held")
        ),
        "cum_exec_qty": Decimal(0),
    }
)


class SweepScope(Enum):
    """The startup sweep's scope when it is not one account. Named, so that an account a caller
    forgot (`None`) is refused and never read as every account (CR-2A-07)."""

    EVERY_ACCOUNT = "every_account"


#: `void_orphans` over every account of every environment: no caller wires it, the startup sweep
#: names each account of its own environment (C-2.11).
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


def request_cutoff(now: datetime, bound_s: float | None) -> datetime | None:
    """The newest `created_at` of a row past its request's bound at `now`, the app clock read
    against the stored `created_at` (as an anchor's age is read, Q-N): an unanswered row
    created then or earlier, `bound_s` seconds old or older, waits for the complete read, and a
    younger one is in flight inside its bound. None when the bound is missing or unusable (not a
    number of seconds, finite, zero or more, that a timestamp can hold): fail closed, as every
    unanswered row then waits (the orchestrator's Q2 ruling). `ValueError` for a naive `now`."""
    require_aware("now", now)
    if isinstance(bound_s, bool) or not isinstance(bound_s, int | float):
        return None
    try:
        if not (math.isfinite(bound_s) and bound_s >= 0):
            return None
        return now - timedelta(seconds=bound_s)
    except OverflowError:  # a bound past what a timestamp holds
        return None


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
#: Awaited once in an insert's transaction, after its rows are written and before its commit, with
#: the rows as stored: the writer's write-ahead audit of the request (`sl.attached`, and
#: `tp.modified` for a take-profit side, 21 Sec.3.3.11 "Audit"), whose record ids the rows carry
#: (`audit_record_id`). A hook that raises, or outlasts the store's audit bound
#: (`WriteAheadTimeout`), leaves nothing written, so the position stays free for the next request.
InsertWriteAhead = Callable[[tuple[RecordedStopRow, ...]], Awaitable[None]]
#: Awaited once in a release and bind's transaction, after both updates and before its commit, with
#: the rows as written (the predecessor, released; the successor, bound): the writer's write-ahead
#: audit (C-2.9). A hook that raises, or outlasts the audit bound (`WriteAheadTimeout`), leaves both
#: rows as they were.
ReleaseWriteAhead = Callable[[tuple[RecordedStopRow, RecordedStopRow]], Awaitable[None]]


#: A `put_in_force` hook, awaited before the commit with every row it changed (replaced first), a
#: `sl.modified` / `tp.modified` record per row; one that fails or is late leaves every row as it
#: was.
InForceWriteAhead = Callable[[tuple[RecordedStopRow, ...]], Awaitable[None]]
#: A `resolve` hook, as `InForceWriteAhead`, given the call's `position_state` too (always for
#: `entry_filled_stop_absent`, CR-S3H0-08; optionally for `in_flight_resolved`; never otherwise), so
#: a void's record names the state the void was given.
ResolveWriteAhead = Callable[[tuple[RecordedStopRow, ...], FillPosition | None], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class InForce:
    """What `put_in_force` wrote: the rows it marked `replaced`, then the rows it put in force."""

    replaced: tuple[RecordedStopRow, ...]
    in_force: tuple[RecordedStopRow, ...]


def check_in_force(account_id: UUID, rows: Sequence[RecordedStopRow]) -> None:
    """`ValueError` before any statement unless `rows` are the account's, of one key, each once."""
    if not rows or len({row.id for row in rows}) != len(rows):
        raise ValueError("a row put in force is named once, and at least one is")
    if len({row.kind for row in rows}) != len(rows):
        raise ValueError("one row in force per key and kind")
    key = (account_id, rows[0].symbol, rows[0].position_idx)
    if any((r.exchange_account_id, r.symbol, r.position_idx) != key for r in rows):
        raise ValueError("the rows put in force are the account's, of one key")


def check_resolve(
    rows: Sequence[RecordedStopRow],
    outcome: ResolveOutcome,
    at: datetime,
    position_state: FillPosition | None,
    write_ahead: ResolveWriteAhead | None,
) -> None:
    """`ValueError` before any statement for rows named twice or none, a naive `at`, a
    `position_state` missing for `entry_filled_stop_absent` (CR-S3H0-08) or given for an answer
    or a replace (`in_flight_resolved` may carry one: the 06:38Z ruling), or a void with no hook
    (C-2.9)."""
    if not rows or len({row.id for row in rows}) != len(rows):
        raise ValueError("a resolve names each row of the request once")
    require_aware("at", at)
    if outcome == "entry_filled_stop_absent" and position_state is None:
        raise ValueError("position_state is required for an entry_filled_stop_absent void")
    if outcome in ("answered", "replaced") and position_state is not None:
        raise ValueError("position_state is a void's, never an answer's or a replace's")
    voids = outcome not in ("answered", "replaced")
    if voids and write_ahead is None:  # 21 Sec.3.3.11: no void unaudited
        raise ValueError("a void is audited write-ahead (C-2.9): no hook was given")


class StaleRecordedStop(OrderStoreError):
    """A settle met a row that is not in flight any more (another writer answered it first) or not
    in the account: nothing was written. Names no value."""

    def __init__(self) -> None:
        super().__init__("a recorded stop is no longer in flight: nothing was written")


class RecordedStopNotBindable(OrderStoreError):
    """A release and bind met rows it may not change (24 Sec.8.3 rule 7): nothing was written.
    Names no value, no id."""

    def __init__(self) -> None:
        super().__init__("a recorded stop cannot take that binding: nothing was written")


class RecordedStopStore(Protocol):
    """The recorded stops' writes and reads; no route reaches it (C-12.4)."""

    async def insert(
        self, stops: Sequence[NewRecordedStop], *, write_ahead: InsertWriteAhead | None = None
    ) -> tuple[RecordedStopRow, ...]:
        """Insert one request's rows in one transaction, all or none, and return them as stored.
        `ValueError` before any statement unless they are one request's (`check_request`);
        `OrderConstraintError(UX_RS_IN_FLIGHT)` when a request is in flight for the position.
        `write_ahead`, when given, is awaited with the rows before the commit, bounded;
        `WriteAheadTimeout` when it outlasts the bound, with nothing written."""
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

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        """The key's live rows, oldest first (`created_at`, then `id`): the `pending` and
        `in_force` ones (`LIVE_STOP_STATUSES`, 21 Sec.13.1 row 45; 24 Sec.8.8 rule 6 has step 3c
        match TP/SL orders against in-force records and open pending ones), whatever their source,
        bound to an exchange order or not, released or not. The store filters on neither: a caller
        sees each row's binding as 24 Sec.8.3 rule 7 leaves it, cleared only by a successor's
        bind. Empty outside the account. Bounded by construction: `ux_rs_in_force` allows one row
        in force per key and kind, `ux_rs_in_flight` one unanswered stop-loss, and a position
        read puts an answered row in force or replaces it, so no `LIMIT`."""
        ...

    async def for_exchange_order(
        self, account_id: UUID, exchange_order_id: str
    ) -> tuple[RecordedStopRow, ...]:
        """The account's rows bound to the exchange order id, any status, oldest first (21
        Sec.13.1 row 46, `ix_rs_exch_id`): an ended row keeps its id, so a stop that closed its
        position still pairs; a released row holds none. 24 Sec.8.3 rule 7 admits one holder at a
        time, but `ix_rs_exch_id` is not unique, so the store reports whatever it holds. The exact
        text only; `ValueError` before any statement unless the id is text of 1 to
        `MAX_EXCHANGE_ORDER_ID_CHARS` characters (`require_exchange_order_id`); empty outside the
        account."""
        ...

    async def release_and_bind(
        self,
        account_id: UUID,
        predecessor_id: UUID,
        successor_id: UUID,
        exchange_order_id: str,
        *,
        at: datetime,
        write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]:
        """24 Sec.8.3 rule 7's one release, with its successor's bind, in one transaction. The
        predecessor, live and bound to this id (an end keeps its id, so an ended row is never
        released), loses it (`released_at` = `at`, never bound again); the successor, live, unbound,
        never released and a later row (by `created_at`, then `id`) of the predecessor's side
        (account, symbol, `position_idx`, kind), takes it if no other row of the account holds it:
        one holder, never two. If either updates no row both roll back and `RecordedStopNotBindable`
        is raised, a replay of a committed pair too. `write_ahead`, the writer's audit (C-2.9), is
        required: awaited with (released, bound) before the commit, bounded; `WriteAheadTimeout`
        leaves both rows as they were. The first holder's bind is the materialising one's."""
        ...

    async def waiting_for_key(
        self,
        account_id: UUID,
        symbol: str,
        position_idx: int,
        *,
        now: datetime,
        bound_s: float | None,
    ) -> tuple[RecordedStopRow, ...]:
        """The key's rows waiting for the complete read (21 Sec.3.3.11), oldest first: every
        `pending` row of any source still unanswered past its request's bound of `bound_s` seconds
        at `now` (`request_cutoff`), and every `pending` entry-attach row of an order of the
        account `WAITING_ENTRY` holds, answered or not, whatever its age. A row in flight inside
        its bound is not listed: a second request meets it at the insert (`ux_rs_in_flight`) and
        retries. A missing or unusable bound lists every unanswered row (fail closed). While any is
        listed, no other stop request for the key may leave: the complete read (slice 3) resolves
        them first. Empty outside the account; `ValueError` for a naive `now`, before any read."""
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

    async def waiting_keys(
        self, account_id: UUID, *, now: datetime, bound_s: float | None
    ) -> tuple[tuple[str, int], ...]:
        """The account's distinct `(symbol, position_idx)` keys with a row `waiting_for_key` would
        list, the oldest row's first: the startup pass's input. `ValueError` for a naive `now`."""
        ...

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        """The key's rows in force (`ux_rs_in_force`: one per kind), by kind; empty elsewhere."""
        ...

    async def database_now(self) -> datetime:
        """The database's clock, aware: the startup floor's start (S3-H's Q7). Reads no row."""
        ...

    async def put_in_force(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        *,
        at: datetime,
        write_ahead: InForceWriteAhead | None = None,
    ) -> InForce:
        """A read showed `rows`' stops (21 Sec.3.3.11): one transaction locks the key's live rows in
        id order, compare-and-sets `rows` (`StaleRecordedStop`), marks `replaced` first the row in
        force and older answered rows of each kind, then puts `rows` in force, `answered_at` kept
        or stamped `at`. `check_in_force` first; the hook is awaited bounded before the commit."""
        ...

    async def resolve(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        outcome: ResolveOutcome,
        *,
        at: datetime,
        position_state: FillPosition | None = None,
        write_ahead: ResolveWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        """Answer or void pending rows, answered or not, each side on its own (CR-S3H0-02), by
        compare-and-set on `(status, answered_at)` and the key as read (`StaleRecordedStop`,
        nothing written). `check_resolve` first; the hook is awaited bounded before the commit,
        given the rows and `position_state`. `replaced` trusts the caller: the store does not
        check that a later row of the key and kind is in force (the complete read decided it)."""
        ...
