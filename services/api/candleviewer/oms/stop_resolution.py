"""The decision of the complete read of a position's waiting stop requests (E29-T04 #913 S3-H;
21-database-schema.md Sec.3.3.11, 24-internal-schemas.md Sec.8.8 rule 6).

A recorded stop left unanswered past its request's bound, or an entry's attach row waiting for the
complete read (`WAITING_ENTRY`), holds its key until that read resolves it. This module decides
what the read showed, purely; the read itself and the writes, through the recorded stops' M14
facade (`RecordedStopRepository`'s `put_in_force` and `resolve`), follow it, and the gate that
asks for it (its cap, its cooldown, its metric and its pages) is slice H3's.

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

Nothing here ends a row, materialises one, binds or releases an `exchange_order_id` or tells B1 a
stop was seen or lost (INV-B1-f).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from candleviewer.exchange.base.models import Order, Position
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow, StopKind

from .commands import LIVE_HISTORY_SPAN_S
from .ports import PositionKey

__all__ = [
    "ENTRY_HELD", "FILL_PAGE", "HISTORY_LEAD_S", "HISTORY_SPAN_S", "RESTORE_HELD", "SPAN_HELD",
    "TRAIL_HELD", "UNSEEN_PAGE", "EntryState", "Move", "Outcome", "PageReason", "PositionState",
    "Reading", "RequestDecision", "StopRequest", "VoidReason", "decide", "full_shows",
    "group_requests", "order_matches", "position_state", "shows_no_stop", "trail_unreadable",
]  # fmt: skip

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
_PARTIAL_KIND: Final[Mapping[StopKind, str]] = {
    "stop_loss": "partial_stop_loss",
    "take_profit": "partial_take_profit",
}


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
