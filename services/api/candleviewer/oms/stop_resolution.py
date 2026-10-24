"""The complete read of a position's waiting stop requests (E29-T04 #913 S3-H;
21-database-schema.md Sec.3.3.11, 24-internal-schemas.md Sec.8.8 rule 6).

A recorded stop left unanswered past its request's bound, or an entry's attach row waiting for the
complete read (`WAITING_ENTRY`), holds its key until that read resolves it. This module decides
what the read showed, purely (1-3), then reads and writes it (4-5) through the recorded stops' M14
facade (`RecordedStopRepository`'s `put_in_force` and `resolve`); the gate that asks for it (its
cap, its cooldown, its metric and its pages) is slice H3's.

1. **Grouping.** The key's waiting rows of the account (C-12.4), `pending`, grouped by request:
   one request's rows come from one INSERT and share `(source, order_id, created_at)` (Q9). A
   `restore` request is E29-T06's: it is decided `held_for_reconciliation`.
2. **Each side's evidence.** A Full side is shown by its position: open on the row's side (a
   position on the other side is `flat`), its stop-loss or take-profit at the trigger; a native
   trail by its distance and its activation price, never by the trigger it moves. No position
   read shows the activation price yet (`exchange.base.models.Position`, `[O-4]`), so a trail
   request whose position shows the trail by its distance is held (`TRAIL_HELD`, the
   orchestrator's 02:11Z ruling), never voided and never put in force; a position that shows no
   stop at all is never held on this rule, and follows the table. A
   Partial side is shown by its bound order open at the venue. An order matches a side when it is
   of its key, closes its side and has its kind, trigger (and, Partial, size), created no earlier
   than 5 s before the request (a bound side: that order alone): an open one; one in history that
   filled, whatever its end status; and one in history that ended with no fill (cancelled,
   deactivated, rejected) only once the position is flat, as while it is open that is the stop
   absent.
3. **The decision**, per request, newest first, so a kind a later request puts in force, or a
   later row of the key already in force (`in_force_for_key`), makes the older rows of that kind
   `replaced`. The precedence: the stop shown, then an order that matches it, then the entry
   still resting, then the fill case, then none. In the fill case (its entry filled, its rows
   answered or not) each side is decided alone: `in_force` when shown, `answered` when an order
   explains it, `replaced`, else `void` with reason `entry_filled_stop_absent`, which pages for a
   stop-loss while the position is open on its side. Any other request is never half voided: one
   side shown puts it in force and answers the other, and one nothing explains goes `void` whole,
   reason `in_flight_resolved`. A history miss decides nothing only where it can hide a match
   (`SPAN_HELD`): a request older than the venue's span (24 Sec.14.1) whose position is flat, or
   older than a demo venue's retention whatever its position, is held; while the position is
   open on its side a live miss past the span still decides, and a key whose position, open on
   either side, shows no stop at all (`shows_no_stop`: no stop-loss, no trail and, when the
   orders were read, no open `partial_stop_loss` or `trailing_stop` order closing it; a
   take-profit is never a stop) is never held on this rule. The rule holds a fill case that would
   void a side as it holds any request. An entry the lookup missed where a miss proves nothing
   (`unseen`) is decided as one `gone`, held only where the rule holds; voided on a position open
   with no stop at all, it pages its stop-loss row (`UNSEEN_PAGE`, the 06:38Z ruling), as the
   fill case pages its open stop-loss (`FILL_PAGE`). An entry partly filled and still resting is
   a fill. A request still listed whose rows the read only matched, all answered already, is held
   by its entry's order (`WAITING_ENTRY`); any other entry's request that leaves a row answered
   or kept, on a row answered already or whose stored order `WAITING_ENTRY` holds
   (`Reading.waiting_entries`), carries `ENTRY_HELD` with its outcome, as that row stays listed.
4. **The read** (`CompleteRead`), every read a `poll` lane read, each bounded at
   `READ_TIMEOUT_S` and the whole at `WHOLE_READ_TIMEOUT_S`: the position always
   (`routing.read_position`); an entry's order by its id among the open orders, then in the
   history from 5 s before its stored `created_ts` (by its bound `exchange_order_id` once it has
   one), credited only when `b01.full_match(found_view(order))` passes (SR-E29-03), so a
   squatter's fill is never the entry's, and `unseen` when not found where a miss proves nothing;
   whether its stored order `WAITING_ENTRY` holds; and, for a Partial side or a Full side whose
   position is flat (Q3), the open orders of the symbol and the order history from 5 s before the
   oldest request, but no earlier than `MAX_HISTORY_WINDOWS` weeks back, to now (the adapter reads
   every 7-day window between, inside the read's bound; an older request is held by the span
   rule, or decided where the position shows no stop), kept to the key and the TP/SL kinds. One
   that fails or does not answer decides nothing (None). The venue's retention comes from its
   port's `ExchangeCapabilities.order_retention_days` (demo 7 d, less rule 6's day; none on
   live), never an environment check (24 Sec.14.2 rule 3). The read keeps no state between calls:
   the cooldown and the attach's reserved slot are H3's gate's.
5. **The writes** (`StopResolver`), each store call bounded at `STORE_TIMEOUT_S`: answers, then
   each request's rows in force (whose transaction also replaces the older answered rows of
   their kind), then the read's own `replaced` rows (an unanswered row, or one whose successor
   was already in force), then the voids, each audited write-ahead (C-2.9), the store giving the
   hook its `position_state` (a fill void's, and a paged unseen entry's, the 06:38Z ruling). A
   write that fails or loses its compare-and-set raises; the key is read again on the next
   request.

Nothing here ends a row, materialises one, binds or releases an `exchange_order_id` or tells B1 a
stop was seen or lost (INV-B1-f).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.exchange.base.models import AccountRef, Order, Position
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import (
    WAITING_ENTRY,
    RecordedStopRow,
    ResolveWriteAhead,
    StopKind,
)

from .commands import LIVE_HISTORY_SPAN_S, found_view
from .fakes import STOP_AUDIT_TIMEOUT_S
from .ports import PositionKey
from .routing import read_position

__all__ = [
    "ENTRY_HELD", "FILL_PAGE", "HISTORY_LEAD_S", "HISTORY_SPAN_S", "MAX_HISTORY_WINDOWS",
    "READ_TIMEOUT_S", "RESTORE_HELD", "SPAN_HELD", "STORE_MARGIN_S", "STORE_TIMEOUT_S",
    "TRAIL_HELD", "UNSEEN_PAGE", "WHOLE_READ_TIMEOUT_S", "CompleteRead", "EntryOrders",
    "EntryState", "Move", "Outcome", "PositionState", "Reading", "RequestDecision",
    "ResolutionStore", "StopRequest", "StopResolver", "VoidAudit", "VoidReason", "VoidWriteAhead",
    "decide", "entry_view", "full_shows", "group_requests", "order_matches", "position_state",
    "shows_no_stop", "trail_unreadable",
]  # fmt: skip

#: Each venue read's bound, and the whole read's, in seconds (the orchestrator's 00:47Z spec).
READ_TIMEOUT_S: Final = 5.0
WHOLE_READ_TIMEOUT_S: Final = 15.0
#: Each store call's bound (21 Sec.3.3.5): the stop audit's write-ahead bound
#: (`STOP_AUDIT_TIMEOUT_S`, the recorded stops' `WRITE_AHEAD_TIMEOUT_S`) plus a margin for the
#: statements around it, so a late audit reaches the caller as the store's `AuditNotDurable`, and
#: only a store call stuck elsewhere (a lock wait, the pool) as this bound's `TimeoutError`.
STORE_MARGIN_S: Final = 2.0
STORE_TIMEOUT_S: Final = STOP_AUDIT_TIMEOUT_S + STORE_MARGIN_S
#: How many of the venue's 7-day history windows one read may walk (Fable, fold 2): 4 weeks, so
#: the adapter's walk stays far inside its cap (106) and the read's bound.
MAX_HISTORY_WINDOWS: Final = 4
#: The order history is read from this long before the request (21 Sec.3.3.11).
HISTORY_LEAD_S: Final = 5.0
#: The venue's history span (24 Sec.14.1, `commands.LIVE_HISTORY_SPAN_S`): an ended order older
#: than it no longer shows, so a miss past it proves nothing.
HISTORY_SPAN_S: Final = LIVE_HISTORY_SPAN_S

#: A request's outcome, as the metric names it (`oms_stop_resolutions_total{outcome}`, 20
#: Sec.12.1); `read_failed` is the gate's, for a read that decided nothing.
type Outcome = Literal[
    "in_force",
    "answered",
    "replaced",
    "entry_resting",
    "held_for_reconciliation",
    "in_flight_resolved",
    "entry_filled_stop_absent",
    "read_failed",
]
type VoidReason = Literal["in_flight_resolved", "entry_filled_stop_absent"]
#: What the decision does with one row: `kept` writes nothing.
type Move = Literal["in_force", "answered", "replaced", "kept", VoidReason]
#: The row's position as the read shows it: `open` on the row's side, else `flat`.
type PositionState = Literal["open", "flat"]
#: An entry's order as the read shows it, the full match passed: still `resting` unfilled,
#: `filled` (any fill, a partly filled entry still resting included), `gone` (ended unfilled, not
#: found, or not the row's order), or `unseen` (not found where a miss proves nothing).
type EntryState = Literal["resting", "filled", "gone", "unseen"]
#: Why a decision pages (`RequestDecision.page_reason`): the fill void of an open stop-loss, or the
#: void of an unseen entry on a position open with no stop at all (the 06:38Z ruling).
type PageReason = Literal["entry_filled_stop_absent", "entry_unseen"]
#: A void's write-ahead hook (`ResolveWriteAhead`, H1): awaited before the commit, with the rows
#: and the `position_state` the store was given (None but for `entry_filled_stop_absent`).
VoidWriteAhead = ResolveWriteAhead

#: Why a request is held for reconciliation (`RequestDecision.held`, the log line's text).
TRAIL_HELD: Final = (
    "a trail request stays held until E29-T06's pass or until Position carries the activation"
    " price (E29-K01)"
)
SPAN_HELD: Final = (
    "a history miss past the venue's span could hide a match: held for E29-T06's pass"
)
RESTORE_HELD: Final = "a restore request is E29-T06's: held for its pass"
ENTRY_HELD: Final = "answered rows its entry's order still holds: held for E29-T06's pass"
#: Why a decision pages (`RequestDecision.page`, H3's page text): `<reason>: <what is exposed>`.
FILL_PAGE: Final = (
    "entry_filled_stop_absent: a stop-loss voided while its position is open on its side (C-2.6)"
)
UNSEEN_PAGE: Final = (
    "entry_unseen: rows voided while the position is open with no stop at all (C-2.6)"
)
#: The open orders that count as a stop for `shows_no_stop` (Partial-mode protection and a
#: trail). A Full-mode `stop_loss` order is left out: the position's own `stop_loss` shows it.
_STOP_ORDERS: Final = frozenset({"partial_stop_loss", "trailing_stop"})

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_LEAD_US: Final = round(HISTORY_LEAD_S * 1_000_000)
_DAY_US: Final = 86_400_000_000
_WEEK_US: Final = 7 * _DAY_US
_PARTIAL_KIND: Final[Mapping[StopKind, str]] = {
    "stop_loss": "partial_stop_loss",
    "take_profit": "partial_take_profit",
}
_STOP_KINDS: Final = frozenset({"trailing_stop", *_PARTIAL_KIND, *_PARTIAL_KIND.values()})
_VOIDS: Final[tuple[VoidReason, ...]] = ("in_flight_resolved", "entry_filled_stop_absent")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StopRequest:
    """One stop request's waiting rows: one INSERT's, stop-loss first (Q9)."""

    source: str
    order_id: UUID | None
    created_at: datetime
    rows: tuple[RecordedStopRow, ...]


@dataclass(frozen=True, slots=True)
class Reading:
    """What the complete read showed of one key: its position, each entry's order, the key's
    TP/SL orders open and in history since the oldest request (empty when not read), the key's
    rows in force, and the oldest times, in microseconds, a miss proves anything at: in the
    history span (an ended order) and in the venue's retention (any order; 0 where it never
    expires). `orders_read` says the TP/SL orders were read; `waiting_entries` names the entries
    whose stored order `WAITING_ENTRY` holds, so their answered rows stay listed."""

    position: Position | None
    entries: Mapping[UUID, EntryState]
    open_orders: tuple[Order, ...] = ()
    history: tuple[Order, ...] = ()
    in_force: tuple[RecordedStopRow, ...] = ()
    history_from_us: int = 0
    retention_from_us: int = 0
    orders_read: bool = False
    waiting_entries: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class RequestDecision:
    """One request's decision: each row's move, the outcome the metric counts, the position as
    the read showed it, the stop-loss rows whose void pages (an open position, H3), and why a
    held request is held or why rows it leaves stay listed."""

    request: StopRequest
    outcome: Outcome
    moves: tuple[tuple[RecordedStopRow, Move], ...]
    position_state: PositionState
    pages: tuple[UUID, ...] = ()
    #: Why a `held_for_reconciliation` request is held, and until when, or, with any outcome,
    #: `ENTRY_HELD` for rows it leaves listed through their entry's order: the log line's text.
    held: str | None = None
    #: Why `pages` pages (`FILL_PAGE`, `UNSEEN_PAGE`); None when nothing pages.
    page: str | None = None
    #: The same, typed, for code to branch on: None when nothing pages.
    page_reason: PageReason | None = None


# --- grouping and the pure matchers ----------------------------------------------------------


def group_requests(key: PositionKey, rows: Sequence[RecordedStopRow]) -> tuple[StopRequest, ...]:
    """`rows` of the key's account, symbol and index that are `pending`, grouped by request
    (`source`, `order_id`, `created_at`), oldest first; any other row is dropped (C-12.4)."""
    place = (key.account_id, key.symbol, key.position_idx)
    groups: dict[tuple[str, UUID | None, datetime], list[RecordedStopRow]] = {}
    for row in rows:
        if (row.exchange_account_id, row.symbol, row.position_idx) == place:
            if row.status == "pending":
                groups.setdefault((row.source, row.order_id, row.created_at), []).append(row)
    return tuple(
        StopRequest(source, order_id, created_at, tuple(sorted(group, key=_kind_order)))
        for (source, order_id, created_at), group in sorted(
            groups.items(), key=lambda item: (item[0][2], item[0][0], str(item[0][1]))
        )
    )


def _kind_order(row: RecordedStopRow) -> tuple[bool, str]:
    return (row.kind != "stop_loss", str(row.id))


def position_state(row: RecordedStopRow, position: Position | None) -> PositionState:
    """`open` when the position holds a size on the row's side, else `flat`: none on its side,
    the other side's included (a one-way reversal)."""
    if position is None or position.qty <= 0 or position.side != row.position_side.lower():
        return "flat"
    return "open"


def full_shows(row: RecordedStopRow, position: Position | None) -> bool:
    """A Full side the position shows: open on the row's side, its stop-loss or take-profit at
    the trigger. Never a trail: it is shown only by its distance and activation price."""
    if row.tpsl_mode != "Full" or position is None or position_state(row, position) != "open":
        return False
    if row.kind == "take_profit":
        return position.take_profit == row.trigger_price
    return row.trailing_distance is None and position.stop_loss == row.trigger_price


def trail_unreadable(row: RecordedStopRow, position: Position | None) -> bool:
    """A trail whose distance the open position shows: no read shows its activation price yet
    (`[O-4]`), so it can be neither shown nor taken for absent, and is held."""
    return (
        row.tpsl_mode == "Full"
        and row.trailing_distance is not None
        and position is not None
        and position_state(row, position) == "open"
        and position.trailing_stop_distance == row.trailing_distance
    )


def shows_no_stop(position: Position | None, open_orders: Sequence[Order] | None = None) -> bool:
    """A position open on either side that shows no stop at all: no stop-loss, no trail, and, when
    the orders were read (`open_orders` not None), no open `partial_stop_loss` or `trailing_stop`
    order of its key closing it (the orchestrator's ruling); a take-profit protects nothing
    (C-2.6). A history miss never holds its key."""
    if position is None or position.qty <= 0:
        return False
    if position.stop_loss is not None or position.trailing_stop_distance is not None:
        return False
    closing = "sell" if position.side == "buy" else "buy"
    place = (position.account_id, position.symbol, position.position_idx)
    return not any(
        (o.account_id, o.symbol, o.position_idx) == place
        and o.side == closing
        and o.order_kind in _STOP_ORDERS
        for o in open_orders or ()
    )


def order_matches(row: RecordedStopRow, order: Order, *, since_us: int) -> bool:
    """An order of the row's key that closes its side, created since `since_us`, of the row's
    kind: a Partial one at its trigger and size, a Full one at its trigger, a trail by its kind
    (an order shows no distance)."""
    closing = "sell" if row.position_side == "Buy" else "buy"
    place = (order.account_id, order.symbol, order.position_idx)
    if place != (row.exchange_account_id, row.symbol, row.position_idx):
        return False
    if order.side != closing or order.created_at < since_us:
        return False
    if row.tpsl_mode == "Partial":
        return (
            order.order_kind == _PARTIAL_KIND[row.kind]
            and order.trigger_price == row.trigger_price
            and order.qty == row.size
        )
    if row.trailing_distance is not None:
        return order.order_kind == "trailing_stop"
    return order.order_kind == row.kind and order.trigger_price == row.trigger_price


type _Evidence = Literal["shown", "matched", "held", "none"]


def _evidence(row: RecordedStopRow, reading: Reading, state: PositionState) -> _Evidence:
    """One side's evidence. A bound side is its bound order's alone: open, shown; fired, a
    match; ended unfilled, a match once flat and the stop absent while open."""
    if trail_unreadable(row, reading.position):
        return "held"
    bound = row.exchange_order_id
    if full_shows(row, reading.position):
        return "shown"
    if bound is not None:
        if any(o.exchange_order_id == bound for o in reading.open_orders):
            return "shown" if row.tpsl_mode == "Partial" else "matched"
        ended = [o for o in reading.history if o.exchange_order_id == bound]
    else:
        since = _us(row.created_at) - _LEAD_US
        if any(order_matches(row, o, since_us=since) for o in reading.open_orders):
            return "matched"
        ended = [o for o in reading.history if order_matches(row, o, since_us=since)]
    if any(o.filled_qty > 0 or o.state == "filled" or state == "flat" for o in ended):
        return "matched"
    return "none"


def _us(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


# --- the decision ----------------------------------------------------------------------------


def decide(requests: Sequence[StopRequest], reading: Reading) -> tuple[RequestDecision, ...]:
    """Each request's decision, oldest first, decided newest first: a kind a later request puts
    in force replaces the older rows of that kind, as a later row already in force does. Pure."""
    later: set[StopKind] = set()
    decided: list[RequestDecision] = []
    for request in reversed(requests):
        stored = {r.kind for r in reading.in_force if r.created_at > request.created_at}
        decision = _decide(request, reading, frozenset(later | stored))
        later |= {row.kind for row, move in decision.moves if move == "in_force"}
        decided.append(decision)
    return tuple(reversed(decided))


def _decide(request: StopRequest, reading: Reading, later: frozenset[StopKind]) -> RequestDecision:
    decision = _moves(request, reading, later)
    if decision.held is not None or request.source != "entry_attach":
        return decision
    waits = request.order_id in reading.waiting_entries
    if any(
        move in ("answered", "kept") and (row.answered_at is not None or waits)
        for row, move in decision.moves
    ):  # the row stays listed through its entry's order (Fable Major, H lens)
        return replace(decision, held=ENTRY_HELD)
    return decision


def _moves(request: StopRequest, reading: Reading, later: frozenset[StopKind]) -> RequestDecision:
    rows = request.rows
    state = position_state(rows[0], reading.position)
    evidence = {r.id: _evidence(r, reading, state) for r in rows}
    if request.source == "restore":
        return _held(request, state, RESTORE_HELD)
    if "held" in evidence.values():
        return _held(request, state, TRAIL_HELD)
    shown = {i for i, e in evidence.items() if e == "shown"}
    matched = {i for i, e in evidence.items() if e == "matched"}
    entry = reading.entries.get(request.order_id) if request.order_id is not None else None
    if entry == "filled":
        filled = _filled(request, state, shown, matched, later)
        voids = any(move == "entry_filled_stop_absent" for _, move in filled.moves)
        if voids and _missed(request, reading, state):  # Opus Major 1, H lens
            return _held(request, state, SPAN_HELD)
        return filled
    if shown:
        moves = tuple(
            (r, _later_or(r, later, "in_force" if r.id in shown else "answered")) for r in rows
        )
        return _decision(request, state, moves)
    if any(r.kind in later for r in rows):  # a later row in force: nothing here is voided
        return _decision(request, state, tuple((r, _later_or(r, later, "answered")) for r in rows))
    if matched:
        if all(r.answered_at is not None for r in rows):  # still listed: its entry's order holds it
            return _held(request, state, ENTRY_HELD)
        return _whole(request, state, "answered", "answered")
    if entry == "resting":
        return _whole(request, state, "kept", "entry_resting")
    if _missed(request, reading, state):
        return _held(request, state, SPAN_HELD)  # a miss there could hide a match
    voided = _whole(request, state, "in_flight_resolved", "in_flight_resolved")
    if entry == "unseen" and _no_stop(reading):  # the 06:38Z ruling: void, and page
        stops = tuple(r.id for r in rows if r.kind == "stop_loss")
        if not stops:
            return voided
        return replace(voided, pages=stops, page=UNSEEN_PAGE, page_reason="entry_unseen")
    return voided


def _missed(request: StopRequest, reading: Reading, state: PositionState) -> bool:
    """A miss that proves nothing, unless the position shows no stop at all: past the span while
    flat, or past a demo venue's retention."""
    since = _us(request.created_at) - _LEAD_US
    past = (
        since < reading.history_from_us and state == "flat"
    ) or since < reading.retention_from_us
    return past and not _no_stop(reading)


def _no_stop(reading: Reading) -> bool:
    return shows_no_stop(reading.position, reading.open_orders if reading.orders_read else None)


def _filled(
    request: StopRequest,
    state: PositionState,
    shown: set[UUID],
    matched: set[UUID],
    later: frozenset[StopKind],
) -> RequestDecision:
    """The fill case, each side alone, answered or not (SEC-S3H0-01): a fill never voids a side
    an order explains, and a stop-loss void pages while the position is open on its side."""
    moves: list[tuple[RecordedStopRow, Move]] = []
    for row in request.rows:
        if row.id in shown:
            move: Move = "in_force"
        elif row.id in matched:
            move = "answered"
        else:
            move = "entry_filled_stop_absent"
        moves.append((row, _later_or(row, later, move)))
    return _decision(request, state, tuple(moves))


def _later_or(row: RecordedStopRow, later: frozenset[StopKind], move: Move) -> Move:
    return "replaced" if row.kind in later else move


def _whole(
    request: StopRequest,
    state: PositionState,
    move: Move,
    outcome: Outcome,
    held: str | None = None,
) -> RequestDecision:
    moves = tuple((r, move) for r in request.rows)
    return RequestDecision(request, outcome, moves, state, held=held)


def _held(request: StopRequest, state: PositionState, held: str) -> RequestDecision:
    return _whole(request, state, "kept", "held_for_reconciliation", held)


def _decision(
    request: StopRequest,
    state: PositionState,
    moves: tuple[tuple[RecordedStopRow, Move], ...],
) -> RequestDecision:
    """The outcome a mixed request counts: a void first, then in force, replaced, answered."""
    made = {move for _, move in moves}
    order: tuple[Outcome, ...] = ("entry_filled_stop_absent", "in_force", "replaced")
    outcome: Outcome = next((named for named in order if named in made), "answered")
    pages = tuple(
        r.id
        for r, move in moves
        if move == "entry_filled_stop_absent" and r.kind == "stop_loss" and state == "open"
    )
    if not pages:
        return RequestDecision(request, outcome, moves, state)
    reason: PageReason = "entry_filled_stop_absent"
    return RequestDecision(
        request, outcome, moves, state, pages, page=FILL_PAGE, page_reason=reason
    )


# --- the ports the read and the writes take --------------------------------------------------


class ResolutionStore(Protocol):
    """The recorded stops' calls the resolution makes, as H1 names them, each scoped by the
    account it is given (C-12.4)."""

    async def waiting_for_key(
        self,
        account_id: UUID,
        symbol: str,
        position_idx: int,
        *,
        now: datetime,
        bound_s: float | None,
    ) -> Sequence[RecordedStopRow]: ...

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> Sequence[RecordedStopRow]: ...

    async def put_in_force(
        self, account_id: UUID, rows: Sequence[RecordedStopRow], *, at: datetime
    ) -> object: ...

    async def resolve(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        outcome: Literal["answered", "replaced", VoidReason],
        *,
        at: datetime,
        write_ahead: VoidWriteAhead | None = None,
        position_state: PositionState | None = None,
    ) -> Sequence[RecordedStopRow]: ...


class EntryOrders(Protocol):
    """The stored orders (`OrderRepository.get`): an entry's row, None outside the account."""

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...


class VoidAudit(Protocol):
    """The write-ahead hook of a void (C-2.9): one `sl.modified` / `tp.modified` record per row,
    with `reason`, actor `system:oms`, ids only (21 Sec.3.3.11 "Audit")."""

    def hook(self, reason: VoidReason) -> VoidWriteAhead: ...


def entry_view(row: OrderRow) -> dict[str, Any]:
    """The stored entry as B1's context names it for `b01.full_match` (24 Sec.8.1): ids, text,
    `reduce_only`, and money as canonical decimal text."""
    money = {
        key: None if value is None else _decimal_text(value)
        for key, value in (
            ("qty", row.qty),
            ("price", row.price),
            ("trigger_price", row.trigger_price),
            ("stop_loss", row.stop_loss),
            ("take_profit", row.take_profit),
        )
    }
    return {
        "order_id": str(row.id),
        "order_link_id": row.order_link_id,
        "account_id": str(row.exchange_account_id),
        "symbol": row.symbol,
        "side": row.side.lower(),
        "reduce_only": row.reduce_only,
        **money,
    }


def _decimal_text(value: Decimal) -> str:
    out = format(value, "f")
    out = out.rstrip("0").rstrip(".") if "." in out else out
    return "0" if out == "-0" else out


# --- the read --------------------------------------------------------------------------------


class CompleteRead:
    """The venue read of one key (24 Sec.8.8 rule 6), in the `poll` lane: the position; each
    entry's order, credited only on its full match; and the key's TP/SL orders when a side needs
    them. None when any read fails or outlasts its bound: nothing is decided on half a read."""

    def __init__(
        self,
        orders: EntryOrders,
        *,
        read_timeout_s: float = READ_TIMEOUT_S,
        whole_timeout_s: float = WHOLE_READ_TIMEOUT_S,
    ) -> None:
        self._orders = orders
        self._read_timeout_s = read_timeout_s
        self._whole_timeout_s = whole_timeout_s

    async def read(
        self,
        port: TradingPort,
        account: AccountRef,
        key: PositionKey,
        requests: Sequence[StopRequest],
        *,
        now: datetime,
    ) -> Reading | None:
        """The key's reading at `now`, or None when a read fails or outlasts its bound."""
        if account.account_id != key.account_id:
            raise ValueError("the account read is the key's (C-12.4)")
        now_us = _us(now)
        days = port.capabilities.order_retention_days  # a demo venue's retention; None on live
        kept = 0 if days is None else now_us - (days - 1) * _DAY_US  # rule 6's margin of a day
        span = now_us - round(HISTORY_SPAN_S * 1_000_000)
        try:
            async with asyncio.timeout(self._whole_timeout_s):
                reading = await self._read(port, account, key, requests, now_us, max(span, kept))
        except Exception as exc:  # CancelledError is no Exception: a cancel goes through
            _log().warning("oms_stop_read_failed", symbol=key.symbol, failure=type(exc).__name__)
            return None
        read_from = reading.history_from_us if reading.orders_read else 0
        return replace(reading, history_from_us=max(span, read_from), retention_from_us=kept)

    async def _read(
        self,
        port: TradingPort,
        account: AccountRef,
        key: PositionKey,
        requests: Sequence[StopRequest],
        now_us: int,
        proves_from_us: int,
    ) -> Reading:
        position = await self._one(read_position(port, account, key.symbol, key.position_idx))
        entries: dict[UUID, EntryState] = {}
        waiting: set[UUID] = set()
        for request in requests:
            if request.source == "entry_attach" and request.order_id is not None:
                row = await self._one(self._orders.get(account.account_id, request.order_id))
                if row is not None and _waits(row):
                    waiting.add(row.id)
                entries[request.order_id] = await self._entry(port, account, row, proves_from_us)
        rows = [row for request in requests for row in request.rows]
        if not any(r.tpsl_mode == "Partial" or position_state(r, position) == "flat" for r in rows):
            return Reading(position, entries, waiting_entries=frozenset(waiting))
        oldest = _us(min(r.created_at for r in rows)) - _LEAD_US
        start = max(oldest, now_us - MAX_HISTORY_WINDOWS * _WEEK_US)  # a bounded walk
        open_now = await self._one(port.open_orders(account, key.symbol))
        history = await self._one(port.order_history(account, start=start, end=now_us))
        place = (key.account_id, key.symbol, key.position_idx)

        def kept(orders: Sequence[Order]) -> tuple[Order, ...]:
            return tuple(
                o
                for o in orders
                if (o.account_id, o.symbol, o.position_idx) == place and o.order_kind in _STOP_KINDS
            )

        return Reading(
            position, entries, kept(open_now), kept(history), history_from_us=start,
            orders_read=True, waiting_entries=frozenset(waiting),
        )  # fmt: skip

    async def _entry(
        self, port: TradingPort, account: AccountRef, row: OrderRow | None, proves_from_us: int
    ) -> EntryState:
        """The entry's order: `gone` when it is not stored for the account, not found, or found
        and not the row's (a squatter's fill is never ours); `unseen` when not found where a miss
        proves nothing (stored before `proves_from_us`); `filled` on any fill, resting or not."""
        if row is None:
            return "gone"
        start = _us(row.created_ts) - _LEAD_US
        found = await self._find(port, account, row, start)
        if found is None:
            if start < proves_from_us:  # a miss there proves nothing (Fable Minor: logged)
                _log().warning("oms_stop_read_entry_unseen", order_link_id=row.order_link_id)
                return "unseen"
            return "gone"
        order, source = found
        bound = row.exchange_order_id
        try:
            ours = b01.full_match(entry_view(row), found_view(order))
        except ValueError:  # malformed money, which B1's guards deny too
            ours = False
        if not ours or (bound is not None and order.exchange_order_id != bound):
            _log().warning("oms_stop_read_entry_unmatched", order_link_id=row.order_link_id)
            return "gone"
        if order.filled_qty > 0:  # a partly filled entry still resting is a fill (the ruling)
            return "filled"
        return "resting" if source == "realtime" else "gone"

    async def _find(
        self, port: TradingPort, account: AccountRef, row: OrderRow, start: int
    ) -> tuple[Order, Literal["realtime", "history"]] | None:
        """The entry's id among the open orders, then in the history from `start` (its bound
        `exchange_order_id` once it has one): the venue's 7 days from it hold its creation."""
        link, bound = row.order_link_id, row.exchange_order_id
        listed = await self._one(port.open_orders(account, row.symbol, order_link_id=link))
        opened = [o for o in listed if o.order_link_id == link]  # the port's filter, again
        if opened:
            return opened[0], "realtime"
        if bound is not None:
            history = port.order_history(account, exchange_order_id=bound, start=start)
        else:
            history = port.order_history(account, order_link_id=link, start=start)
        found = await self._one(history)
        ended = [o for o in found if o.order_link_id == link or o.exchange_order_id == bound]
        return (ended[0], "history") if ended else None

    async def _one[T](self, call: Awaitable[T]) -> T:
        async with asyncio.timeout(self._read_timeout_s):
            return await call


def _waits(row: OrderRow) -> bool:
    """`WAITING_ENTRY` on the stored order: each column holds its value, or one of a set."""
    for name, value in WAITING_ENTRY.items():
        held = getattr(row, name)
        if not (held in value if isinstance(value, frozenset) else held == value):
            return False
    return True


# --- the resolution --------------------------------------------------------------------------


class StopResolver:
    """One key's resolution: its waiting rows re-read, grouped, read at the venue, decided and
    written. The gate (H3) runs one per key at a time, bounds it and counts its outcomes."""

    def __init__(
        self,
        store: ResolutionStore,
        read: CompleteRead,
        audit: VoidAudit,
        *,
        now: Callable[[], datetime],
        store_timeout_s: float = STORE_TIMEOUT_S,
    ) -> None:
        self._store = store
        self._read = read
        self._audit = audit
        self._now = now
        self._store_timeout_s = store_timeout_s

    async def resolve_key(
        self, port: TradingPort, account: AccountRef, key: PositionKey, *, bound_s: float | None
    ) -> tuple[RequestDecision, ...] | None:
        """The key's decisions, written; None when the read decided nothing (`read_failed`).
        A store read or write that fails raises, with what was written before it kept: a void
        audit past its bound as `AuditNotDurable`, a store call past `STORE_TIMEOUT_S` as
        `TimeoutError`, a lost compare-and-set as `StaleRecordedStop`."""
        if account.account_id != key.account_id:
            raise ValueError("the account resolved is the key's (C-12.4)")
        now = self._now()
        listed = await self._bounded(
            self._store.waiting_for_key(
                key.account_id, key.symbol, key.position_idx, now=now, bound_s=bound_s
            )
        )
        requests = group_requests(key, listed)
        if not requests:
            return ()
        live = [r for r in requests if r.source != "restore"]
        reading = Reading(None, {})
        if live:
            read = await self._read.read(port, account, key, live, now=now)
            if read is None:
                return None
            stored = await self._bounded(
                self._store.in_force_for_key(key.account_id, key.symbol, key.position_idx)
            )
            reading = replace(read, in_force=tuple(stored))
        decisions = decide(requests, reading)
        await self._write(key, decisions)
        for d in decisions:
            _log().info(
                "oms_stop_request_resolved",
                symbol=key.symbol,
                outcome=d.outcome,
                rows=[str(row.id) for row, _ in d.moves],
                pages=[str(i) for i in d.pages],
            )
            if d.held is not None:  # H3 counts it and keeps one line per key
                _log().warning("oms_stop_request_held", symbol=key.symbol, reason=d.held)
        return decisions

    async def _write(self, key: PositionKey, decisions: Sequence[RequestDecision]) -> None:
        """Answers, rows in force (replacing the older answered rows of their kind), the read's
        own `replaced` rows, then voids, each audited write-ahead. Never an end, a bind or a
        release."""
        at, account_id = self._now(), key.account_id
        put = {r.kind: r.created_at for d in decisions for r, m in d.moves if m == "in_force"}
        for d in decisions:
            rows = [r for r, m in d.moves if m == "answered" and r.answered_at is None]
            if rows:
                await self._bounded(self._store.resolve(account_id, rows, "answered", at=at))
        for d in decisions:
            shown = [r for r, m in d.moves if m == "in_force"]
            if shown:
                await self._bounded(self._store.put_in_force(account_id, shown, at=at))
        for d in decisions:  # the put's transaction replaced an older answered row of its kind
            rows = [r for r, m in d.moves if m == "replaced" and not _put_replaced(r, put)]
            if rows:
                await self._bounded(self._store.resolve(account_id, rows, "replaced", at=at))
        for d in decisions:
            for reason in _VOIDS:
                voided = [r for r, m in d.moves if m == reason]
                if voided:
                    stated = reason == "entry_filled_stop_absent" or d.page == UNSEEN_PAGE
                    state = d.position_state if stated else None
                    await self._bounded(
                        self._store.resolve(
                            account_id,
                            voided,
                            reason,
                            at=at,
                            write_ahead=self._audit.hook(reason),
                            position_state=state,
                        )
                    )

    async def _bounded[T](self, call: Awaitable[T]) -> T:
        async with asyncio.timeout(self._store_timeout_s):
            return await call


def _put_replaced(row: RecordedStopRow, put: Mapping[StopKind, datetime]) -> bool:
    """An answered row older than a row of its kind this read puts in force: that put replaced
    it in its own transaction (`put_in_force`)."""
    born = put.get(row.kind)
    return row.answered_at is not None and born is not None and row.created_at < born
