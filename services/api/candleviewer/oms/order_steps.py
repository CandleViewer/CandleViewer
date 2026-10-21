"""B1's write-ahead step (E29-T03 #847): the `b01_order.PersistPort` over the OMS's repositories.

`persist_event` hands every `lifecycle` step of an order machine here before the machine moves on
(24-internal-schemas.md Sec.8.2 S8), and the step commits in one unit of work or not at all (S7):

* the first step creates the row (`OrderRepository.create`), at `validated` (24 Sec.8.4), at
  `untracked`, or at `submitted` for a recorded stop's TP/SL order (Sec.8.3 rule 7), from the
  order the OMS registered with `expect` before it sent `VALIDATE`, `DISCOVERED` or
  `MATERIALISED`; the registered order must be the one the machine stamped. An `untracked` row's
  provenance is `reconciliation` and a `submitted` one's `recorded_stop`. E29-T04's pipeline
  registers a `validated` order with its `FirstPersist`, and the row is then written with its
  group, recorded stops and anchor in one transaction (`SubmissionRepository.create_first`,
  21 Sec.3.3.10);
* a step that applies a fill (an `EXEC`, or a reconciliation finding that carries the execution)
  commits the execution, the totals the machine computed, the state and the fill event together
  (`ExecutionRepository.commit_fill`). An `exec_id` stored already refuses it, as the machine has
  just counted it (S4): for an `EXEC` whose execution this order holds as `StaleOrderState`, since
  the row holds a fill the machine did not know, so the facade rebuilds the machine from the row
  (24 Sec.8.2 S7); for one another order holds (hostile or misrouted, OM-T04), and for a
  finding, as a `ValueError`, which rebuilds nothing; for one whose holder is not read within
  `HOLDER_READ_TIMEOUT` as `HolderNotRead`, which rebuilds nothing either and which a later
  delivery may pass;
* any other step is a compare-and-set of the state with its event (`OrderRepository.transition`).
  A `filled` step needs its execution: the store refuses `filled` without one (OM-R02).

Every step stores the chart state in `lifecycle_state` beside `state` (24 Sec.8.2 mapping), the
exchange order id the machine bound (SR-E29-03), the terms an accepted amend changed (S2: only once
the exchange accepts them), the event's kind and source (an exchange source carries its message,
OM-R02) and the result's code on the event. A step into `rejected` stores its reject code as the
event's `ret_code` and as `reject_code` alike (`OrderTransition`), so a fold of the events rebuilds
the reject columns (`oms.recovery`).

E29-T04 (24 Sec.8.4): the send's step (`validated` -> `submitting`) sets `idempotency_state` to
`in_flight` and counts `submit_attempts` up; a step out of `submitting` or `unknown` that answers
the create sets `acked` or `failed`, and `unknown` keeps `in_flight` (`idempotency_of`). Each step
also settles the entry's recorded stops in its own transaction, as 21 Sec.3.3.11's table says
(`entry_stop_settle`, R10): `answered` once the order is accepted or fills; `void` only for an
entry never sent (a KILL out of `validated`) or on an end the exchange confirmed unfilled (the
create's own refusal, or an exchange-confirmed terminal with zero count: the order's own end push,
`cancelled` or `expired`, reporting a zero cumulative fill); and every other end, a KILL after the
send and any end out of `unknown` among them, leaves them `pending`, waiting for the complete read
(24 Sec.8.8 rule 6), which settles them from what the exchange shows. An attach row is never voided
blind (C-2.6): B1's own `filled_qty` can lag a fill the exchange holds back, and that fill is a
position whose attach stop the read must find. "Never sent" is write-ahead: the send's step
commits its attempt before the create can leave (B1 arms `submitting`'s place only once that
entry's write committed), so a KILL out of `validated` meets an order no request has sent. A
reduce-only order records none.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Final, Literal, cast, get_args
from uuid import UUID

from candleviewer.statechart.bindings.b01_order import FIRST_ROWS, Step
from candleviewer.statechart.config import CV_PERSIST_TIMEOUT
from candleviewer.storage.repositories.executions import (
    ExecType,
    FillTotals,
    NewExecution,
    OrderFill,
)
from candleviewer.storage.repositories.orders import (
    AMENDABLE,
    FILL_KINDS,
    ORDER_STATE_OF,
    EntryStopSettle,
    IdempotencyState,
    LifecycleState,
    NewOrder,
    NewOrderEvent,
    OrderEventKind,
    OrderEventSource,
    OrderProvenance,
    OrderTransition,
    StaleOrderState,
)
from candleviewer.storage.repositories.submissions import FirstPersist

from .errors import HolderNotRead
from .repository import ExecutionRepository, OrderRepository, SubmissionRepository

__all__ = [
    "HOLDER_READ_TIMEOUT", "MAX_EXPECTED", "EntryStopEffect", "OrderStepWriter",
    "entry_stop_settle", "event_kind", "idempotency_of",
]  # fmt: skip

#: What a step does to its entry's recorded stops (21 Sec.3.3.11's table, R10): `answered` and
#: `void` name the settle statement it runs in its own transaction; `waiting` runs none and leaves
#: them `pending`, waiting for the complete read (24 Sec.8.8 rule 6), which alone settles them
#: from what the exchange shows.
EntryStopEffect = Literal["answered", "void", "waiting"]

#: Orders registered for their first step and not yet written, the oldest dropped first (C-2.18).
MAX_EXPECTED: Final = 1024
#: Seconds the read of which order holds a stored `exec_id` may take, a quarter of the step's
#: `CV_PERSIST_TIMEOUT` (C-2.18): the step wrote nothing, so a read that does not answer in time
#: refuses it (`HolderNotRead`), as a store that did not serve would, never as an outcome in doubt
#: or as a refusal of the fill's own data.
HOLDER_READ_TIMEOUT: Final = CV_PERSIST_TIMEOUT / 4
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: Wide enough that a fill's value, qty times price, is exact before the column check refuses it.
_EXACT: Final = Context(prec=80)
_SIDES: Final = {"buy": "Buy", "sell": "Sell"}
_EXEC_TYPES: Final[dict[str, ExecType]] = {
    "trade": "Trade",
    "funding": "Funding",
    "adl_trade": "AdlTrade",
    "bust_trade": "BustTrade",
    "settle": "Settle",
}
_SOURCES: Final = frozenset(get_args(OrderEventSource))
_TERMS: Final = ("price", "trigger_price", "take_profit", "stop_loss")
_FINDINGS: Final = ("RECON_FOUND_LIVE", "RECON_FOUND_PARTIAL", "RECON_FOUND_FILLED")
#: The kind and source of each trigger's event (24 Sec.8.2); a payload's `source` names where an
#: exchange fact came from. A `place` result is an `ack` only into `submitted`, and a service
#: that raised is an `error` (S1), so neither is listed.
_KINDS: Final[dict[str, tuple[OrderEventKind, OrderEventSource]]] = {
    "VALIDATE": ("local_create", "local"),
    "DISCOVERED": ("adopt", "reconcile"),
    "MATERIALISED": ("exchange_push", "ws_private"),
    "SEND": ("submit_attempt", "local"),
    "CANCEL": ("cancel_request", "local"),
    "AMEND": ("amend_request", "local"),
    "TRIGGERED": ("exchange_push", "ws_private"),
    "EXPIRE": ("expire", "ws_private"),
    "REMOTE_CANCELLED": ("exchange_push", "ws_private"),
    "AMEND_REJECTED": ("amend_ack", "ws_private"),
    "MISMATCH": ("reconcile_diff", "reconcile"),
    **dict.fromkeys(
        (*_FINDINGS, "RECON_FOUND_CANCELLED", "RECON_MISS"), ("reconcile_diff", "reconcile")
    ),
    "TRANSPORT_FAULT": ("error", "local"),
    "FAULT": ("error", "local"),
    "ADOPT": ("adopt", "local"),
    "OPERATOR_RESOLVED": ("reconcile_diff", "local"),
    "KILL": ("kill", "local"),
    "done.invoke.cancel": ("cancel_ack", "rest"),
    "done.invoke.amend": ("amend_ack", "rest"),
}
#: 24 Sec.8.4: the states the create is in flight in, and what a step out of them says of it.
_SENT: Final = frozenset({"submitting", "unknown"})
_ACKED: Final = frozenset(
    {"submitted", "triggered", "partially_filled", "filled", "cancelled", "expired"}
)
_FAILED: Final = frozenset({"rejected", "held"})
#: 21 Sec.3.3.11: an entry is accepted (or fills) in these, and ends (or is held) in those.
_ANSWERS_STOPS: Final = frozenset({"submitted", "triggered", "partially_filled", "filled"})
_ENDS_ENTRY: Final = frozenset({"rejected", "held", "killed", "cancelled", "expired"})
#: A first row's provenance where its state fixes it (21 Sec.3.3.4): reconciliation records an
#: `untracked` row, and E29-T05 materialises a recorded stop's TP/SL order at `submitted`.
_FIRST_PROVENANCE: Final[Mapping[LifecycleState, OrderProvenance]] = {
    "untracked": "reconciliation",
    "submitted": "recorded_stop",
}
#: The states the exchange's end push confirms an unfilled cancel out of: the exchange took the
#: create, and B1 follows the order's pushes (never `unknown`, `quarantined` or `untracked`).
_ON_THE_BOOK: Final = frozenset(
    {"submitted", "triggered", "partially_filled", "cancel_pending", "amend_pending"}
)
#: An exchange-confirmed terminal with zero count (the orchestrator's rulings of 14:26Z): each end
#: push the exchange sends (B1's `_PUSH` payload, whose `cum_exec_qty` is its cumulative fill) and
#: the end it confirms, which the facade holds until B1 holds every fill it reports (INV-B1-k).
#: Written once, so `cancelled` and `expired` take one rule.
_CONFIRMED_ENDS: Final[Mapping[str, LifecycleState]] = MappingProxyType(
    {"REMOTE_CANCELLED": "cancelled", "EXPIRE": "expired"}
)
#: The settle statement each effect runs in the step's transaction: `waiting` runs none.
_STATEMENTS: Final[Mapping[EntryStopEffect | None, EntryStopSettle]] = MappingProxyType(
    {"answered": "answered", "void": "void"}
)


def idempotency_of(from_state: LifecycleState, to_state: LifecycleState) -> IdempotencyState | None:
    """What the step says of the order's create: sent (`in_flight`), answered (`acked`,
    `failed`), or nothing new (`None`)."""
    if (from_state, to_state) == ("validated", "submitting"):
        return "in_flight"
    if from_state in _SENT and to_state in _ACKED:
        return "acked"
    if from_state in _SENT and to_state in _FAILED:
        return "failed"
    return None


def entry_stop_settle(
    from_state: LifecycleState,
    to_state: LifecycleState,
    filled_qty: Decimal,
    *,
    trigger: str,
    reported_fill: Decimal | None = None,
) -> EntryStopEffect | None:
    """What the step does to the entry's recorded stops, as 21 Sec.3.3.11's table says (R10): the
    first step into acceptance or a fill answers them; an end voids them only when B1 holds no
    fill and the entry was never sent (`_never_sent`) or the exchange confirmed it unfilled
    (`_confirms_unfilled`); every other end (a KILL after the send, an expiry or a cancel with no
    exchange count, any end out of `unknown`, an end reconciliation or the operator decided, a
    hold) leaves them `pending`, waiting for the complete read; anything else changes nothing
    (None). `filled_qty` is B1's count, which can lag a fill the exchange holds back, so its zero
    never voids a row on its own (C-2.6); `reported_fill` is the exchange's own cumulative fill,
    which the push that `trigger` names reported (`cum_exec_qty`), else None."""
    if to_state in _ANSWERS_STOPS:
        return None if from_state in _ANSWERS_STOPS else "answered"
    if to_state not in _ENDS_ENTRY:
        return None
    if filled_qty == 0 and (
        _never_sent(from_state, to_state)
        or _confirms_unfilled(from_state, to_state, trigger, reported_fill)
    ):
        return "void"
    return "waiting"


def _never_sent(from_state: LifecycleState, to_state: LifecycleState) -> bool:
    """A KILL out of `validated` (`abandon`, or the kill switch before the send): the send's step,
    which commits `submit_attempts` before any create can leave, never committed, as this step's
    compare-and-set from `pending_submit` proves, so no request sent the order (the orchestrator's
    rulings of 14:26Z)."""
    return (from_state, to_state) == ("validated", "killed")


def _confirms_unfilled(
    from_state: LifecycleState, to_state: LifecycleState, trigger: str, reported: Decimal | None
) -> bool:
    """An exchange-confirmed end with nothing filled: the create's own answer refused it
    (`submitting` -> `rejected` on `done.invoke.place`), or an exchange-confirmed terminal with
    zero count: the exchange's own end push (`_CONFIRMED_ENDS`, `cancelled` or `expired`) reported
    a zero cumulative fill for an order on its book. A cancel's ack and a locally timed expiry
    report no exchange count, and nothing out of `unknown` is a confirmation: the rows of those
    wait for the complete read."""
    if to_state == "rejected":
        return from_state == "submitting" and trigger == "done.invoke.place"
    return (
        _CONFIRMED_ENDS.get(trigger) == to_state
        and from_state in _ON_THE_BOOK
        and reported is not None
        and reported == 0
    )


class OrderStepWriter:
    """Writes B1's steps through the OMS's repositories; set as `OrderPorts.persist`."""

    def __init__(
        self,
        orders: OrderRepository,
        executions: ExecutionRepository,
        *,
        clock: Callable[[], datetime],
        submissions: SubmissionRepository | None = None,
    ) -> None:
        self._orders = orders
        self._executions = executions
        self._clock = clock
        self._submissions = submissions
        self._expected: OrderedDict[UUID, tuple[NewOrder, FirstPersist | None]] = OrderedDict()

    def expect(self, order: NewOrder, *, first: FirstPersist | None = None) -> None:
        """Register the order the OMS built (E29-T04's pipeline; E29-T06 for one it discovered;
        E29-T05 or E29-T06 for a recorded stop's TP/SL order) before it sends `VALIDATE`,
        `DISCOVERED` or `MATERIALISED`: that step creates the row from it, with `first`'s rows
        when given (a `validated` row only). That step spends the registration, whether it
        writes the row or is refused."""
        self._expected[order.id] = (order, first)
        self._expected.move_to_end(order.id)
        while len(self._expected) > MAX_EXPECTED:
            self._expected.popitem(last=False)

    async def __call__(self, step: Step) -> int:
        """Commit *step* and answer its event's `seq`; raise, with nothing written, otherwise."""
        account, order_id = _uuid(step.account_id), _uuid(step.order_id)
        to_state = _chart_state(step.to_state)
        if step.from_state is None:
            return await self._create(step, account, order_id, to_state)
        from_state = _chart_state(step.from_state)
        kind, source = event_kind(step)
        rejected = to_state == "rejected"
        reject = _text(step.context.get("reject_code")) if rejected else None
        settle = None
        if step.context.get("reduce_only") is not True:  # a reduce-only order records no stop
            filled = _decimal(step.context.get("filled_qty", "0"))
            effect = entry_stop_settle(
                from_state, to_state, filled, trigger=step.event, reported_fill=_reported(step)
            )
            settle = _STATEMENTS.get(effect)  # `waiting`: no statement, the rows stay pending
        move = OrderTransition(
            account_id=account,
            order_id=order_id,
            from_state=ORDER_STATE_OF[from_state],
            to_state=ORDER_STATE_OF[to_state],
            event=NewOrderEvent(
                kind=kind,
                source=source,
                event_ts=self._clock(),
                payload=step.payload,
                ret_code=reject if rejected else _text(step.payload.get("error_code")),
            ),
            reject_code=reject,
            lifecycle_state=to_state,
            exchange_order_id=_text(step.context.get("exchange_order_id")),
            terms=_amended(step),
            idempotency_state=idempotency_of(from_state, to_state),
            bump_submit_attempts=(from_state, to_state) == ("validated", "submitting"),
            entry_stops=settle,
        )
        if kind not in FILL_KINDS:
            return (await self._orders.transition(move)).event.seq
        done = await self._executions.commit_fill(_fill(step, move))
        if done is not None:
            return done.event.seq
        if step.event != "EXEC":
            raise ValueError(
                "the execution is stored already, so the machine counted it twice (S4)"
            )
        try:
            async with asyncio.timeout(HOLDER_READ_TIMEOUT):
                stored = await self._executions.get(account, str(step.payload.get("exec_id")))
        except TimeoutError:
            # Nothing was written: refused, but not for the fill's own data, as a later read may
            # answer. Were it this order's, the machine stays behind its row until one of its
            # writes meets the row.
            raise HolderNotRead("the execution is stored already; its order was not read") from None
        if stored is None or stored.order_id != order_id:
            # Another order's execution under this order's pairing fields: hostile or misrouted
            # (OM-T04), never a row that moved on, so nothing is rebuilt for it.
            raise ValueError("the execution is stored already, for another order")
        # The machine counted as new a fill its row holds: the row moved on under it (a COMMIT that
        # landed after the machine was rebuilt), so the facade rebuilds it again (S7).
        raise StaleOrderState(order_id, move.from_state)

    async def _create(
        self, step: Step, account: UUID, order_id: UUID, to_state: LifecycleState
    ) -> int:
        # The registration is spent by this attempt, written or refused (CR-2A-06): the facade
        # drops a machine whose first step was refused (S7), so nothing would use it again, and a
        # first persist holds the request's key, its fingerprint and the audit hook.
        expected = self._expected.pop(order_id, None)
        if expected is None or FIRST_ROWS.get(to_state) != step.event:
            raise ValueError("no registered order for this order's first row")
        order, first = expected
        _agrees(order, step, account)
        kind, source = event_kind(step)
        event = NewOrderEvent(
            kind=kind, source=source, event_ts=self._clock(), payload=step.payload
        )
        provenance = _FIRST_PROVENANCE.get(to_state, order.provenance)
        stored = replace(
            order,
            state=ORDER_STATE_OF[to_state],
            lifecycle_state=to_state,
            provenance=provenance,
        )
        if first is None:
            await self._orders.create(stored, event)
        elif to_state != "validated" or self._submissions is None:
            raise ValueError("a first persist writes a validated row, through its store")
        else:
            await self._submissions.create_first(first, stored, event)
        return 0  # an order's first event (`OrderStore.create`)


def _uuid(raw: object) -> UUID:
    if not isinstance(raw, str):
        raise ValueError("the step names no order or account")
    return UUID(raw)


def _chart_state(raw: object) -> LifecycleState:
    if raw not in ORDER_STATE_OF:
        raise ValueError("the step names no B1 lifecycle state")
    return cast(LifecycleState, raw)


def _text(raw: object) -> str | None:
    return raw if isinstance(raw, str) else None


def _decimal(raw: object) -> Decimal:
    """The binding's canonical decimal text (`b01_order._text`); anything else is refused."""
    if not isinstance(raw, str):
        raise ValueError("a money value is not decimal text")
    return Decimal(raw)


def _reported(step: Step) -> Decimal | None:
    """The cumulative fill the exchange's own end push reports (`cum_exec_qty`), else None: a
    command's answer, a finding and B1's count report none, and text that is not a finite decimal
    reports none either, so it never voids a row (`entry_stop_settle`)."""
    raw = step.payload.get("cum_exec_qty") if step.event in _CONFIRMED_ENDS else None
    if not isinstance(raw, str):
        return None
    try:
        reported = Decimal(raw)
    except InvalidOperation:
        return None
    return reported if reported.is_finite() else None


def _execution(step: Step) -> Mapping[str, Any] | None:
    """The execution a step applies: an `EXEC`'s payload, or the one a finding carries."""
    if step.event == "EXEC":
        return step.payload
    carried = step.payload.get("execution") if step.event in _FINDINGS else None
    return carried if isinstance(carried, Mapping) else None


def event_kind(step: Step) -> tuple[OrderEventKind, OrderEventSource]:
    """The kind and source of *step*'s `order_events` row (24 Sec.8.2), which the facade's
    `oms_state_transitions_total{source}` reads too; `ValueError` for a trigger with none."""
    declared = step.payload.get("source")
    if _execution(step) is not None:
        fill: OrderEventKind = "fill" if step.to_state == "filled" else "partial_fill"
        if step.event != "EXEC":
            return fill, "reconcile"
        return fill, cast(OrderEventSource, declared) if declared in _SOURCES else "ws_private"
    if step.event.startswith("error.platform."):
        return "error", "local"
    if step.event == "done.invoke.place":
        return ("ack" if step.to_state == "submitted" else "reject"), "rest"
    if step.event not in _KINDS:
        raise ValueError("the step's trigger has no write-ahead event kind")
    kind, source = _KINDS[step.event]
    if source in ("ws_private", "reconcile") and declared in _SOURCES:
        source = cast(OrderEventSource, declared)
    return kind, source


def _amended(step: Step) -> dict[str, Decimal]:
    """An accepted amend's terms as the machine adopted them (`adopt_amend`): the context's value
    of each term the result names, so a refused one writes the prior value back unchanged."""
    result, ctx = step.payload, step.context
    named = result.get("terms") if step.event == "done.invoke.amend" else None
    if result.get("ok") is not True or not isinstance(named, Mapping):
        return {}
    return {key: _decimal(ctx.get(key)) for key in AMENDABLE if key in named and ctx.get(key)}


def _same(column: Decimal | None, raw: object) -> bool:
    if column is None or raw is None:
        return column is None and raw is None
    return column == _decimal(raw)


def _agrees(order: NewOrder, step: Step, account: UUID) -> None:
    """The registered order is the one the machine stamped: its identity and terms (the fields
    SR-E29-03 matches), and for a row created outside the placement path (`untracked`, a recorded
    stop's `submitted`) its exchange order id."""
    ctx = step.context
    same = (
        order.exchange_account_id == account
        and order.order_link_id == step.order_link_id
        and order.symbol == ctx.get("symbol")
        and order.side == _SIDES.get(str(ctx.get("side")))
        and order.reduce_only is ctx.get("reduce_only")
        and _same(order.qty, ctx.get("qty"))
        and all(_same(getattr(order, k), ctx.get(k)) for k in _TERMS)
        and (
            step.to_state == "validated" or order.exchange_order_id == ctx.get("exchange_order_id")
        )
    )
    if not same:
        raise ValueError("the registered order is not the order the machine holds")


def _at(raw: object, fallback: datetime) -> datetime:
    """An execution's `ts_exec` as a time, else `ValueError` (hostile data, OM-T04): one past the
    last instant a `datetime` holds is refused as a malformed one is, never an `OverflowError`."""
    if raw is None:
        return fallback
    if type(raw) is not int or raw < 0:
        raise ValueError("an execution time is not microseconds since the epoch")
    try:
        return _EPOCH + timedelta(microseconds=raw)
    except OverflowError:
        raise ValueError("an execution time is past the last one a datetime holds") from None


def _fill(step: Step, move: OrderTransition) -> OrderFill:
    """The fill's write-ahead unit: its execution (24 Sec.8.1 to the column vocabulary), the
    totals the machine computed (`apply_execution`), and the step."""
    p, ctx = cast(Mapping[str, Any], _execution(step)), step.context
    qty, price, closed = _decimal(p.get("qty")), _decimal(p.get("price")), p.get("closed_pnl")
    execution = NewExecution(
        exchange_account_id=move.account_id,
        exec_id=str(p.get("exec_id")),
        symbol=str(p.get("symbol")),
        side=cast(Any, _SIDES[str(p.get("side"))]),
        exec_qty=qty,
        exec_price=price,
        exec_value=_EXACT.multiply(qty, price),
        exec_type=_EXEC_TYPES[str(p.get("exec_type"))],
        is_maker=p.get("is_maker") is True,
        exec_ts=_at(p.get("ts_exec"), move.event.event_ts),
        order_id=move.order_id,
        order_link_id=step.order_link_id,
        exec_fee=_decimal(p.get("fee")),
        fee_rate=_decimal(p.get("fee_rate")),
        fee_currency=str(p.get("fee_currency") or "USDT"),
        closed_pnl=None if closed is None else _decimal(closed),
        is_paper=move.event.source == "paper",
    )
    totals = FillTotals(
        cum_exec_qty=_decimal(ctx.get("filled_qty")),
        cum_exec_value=_decimal(ctx.get("cum_exec_value")),
        avg_price=_decimal(ctx.get("avg_price")),
        fee_paid=_decimal(ctx.get("fee_paid")),
    )
    return OrderFill(step=move, execution=execution, totals=totals)
