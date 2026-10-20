"""B1's write-ahead step (E29-T03 #847): the `b01_order.PersistPort` over the OMS's repositories.

`persist_event` hands every `lifecycle` step of an order machine here before the machine moves on
(24-internal-schemas.md Sec.8.2 S8), and the step commits in one unit of work or not at all (S7):

* the first step creates the row (`OrderRepository.create`), at `validated` (24 Sec.8.4) or at
  `untracked`, from the order the OMS registered with `expect` before it sent `VALIDATE` or
  `DISCOVERED`; the registered order must be the one the machine stamped;
* a step that applies a fill (an `EXEC`, or a reconciliation finding that carries the execution)
  commits the execution, the totals the machine computed, the state and the fill event together
  (`ExecutionRepository.commit_fill`). An `exec_id` stored already refuses it, as the machine has
  just counted it (S4): for an `EXEC` as `StaleOrderState`, since the row holds a fill the machine
  did not know, so the facade rebuilds the machine from the row (24 Sec.8.2 S7); for a finding as
  a `ValueError`;
* any other step is a compare-and-set of the state with its event (`OrderRepository.transition`).
  A `filled` step needs its execution: the store refuses `filled` without one (OM-R02).

Every step stores the chart state in `lifecycle_state` beside `state` (24 Sec.8.2 mapping), the
exchange order id the machine bound (SR-E29-03), the terms an accepted amend changed (S2: only once
the exchange accepts them), the event's kind and source (an exchange source carries its message,
OM-R02) and the result's code on the event. A step into `rejected` stores its reject code as the
event's `ret_code` and as `reject_code` alike (`OrderTransition`), so a fold of the events rebuilds
the reject columns (`oms.recovery`).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal
from typing import Any, Final, cast, get_args
from uuid import UUID

from candleviewer.statechart.bindings.b01_order import Step
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
    LifecycleState,
    NewOrder,
    NewOrderEvent,
    OrderEventKind,
    OrderEventSource,
    OrderTransition,
    StaleOrderState,
)

from .repository import ExecutionRepository, OrderRepository

__all__ = ["MAX_EXPECTED", "OrderStepWriter", "event_kind"]

#: Orders registered for their first step and not yet written, the oldest dropped first (C-2.18).
MAX_EXPECTED: Final = 1024
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


class OrderStepWriter:
    """Writes B1's steps through the OMS's repositories; set as `OrderPorts.persist`."""

    def __init__(
        self,
        orders: OrderRepository,
        executions: ExecutionRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._orders = orders
        self._executions = executions
        self._clock = clock
        self._expected: OrderedDict[UUID, NewOrder] = OrderedDict()

    def expect(self, order: NewOrder) -> None:
        """Register the order the OMS built (E29-T04's pipeline; E29-T06 for one it discovered)
        before it sends `VALIDATE` or `DISCOVERED`: that step creates the row from it."""
        self._expected[order.id] = order
        self._expected.move_to_end(order.id)
        while len(self._expected) > MAX_EXPECTED:
            self._expected.popitem(last=False)

    async def __call__(self, step: Step) -> int:
        """Commit *step* and answer its event's `seq`; raise, with nothing written, otherwise."""
        account, order_id = _uuid(step.account_id), _uuid(step.order_id)
        to_state = _chart_state(step.to_state)
        if step.from_state is None:
            return await self._create(step, account, order_id, to_state)
        kind, source = event_kind(step)
        rejected = to_state == "rejected"
        reject = _text(step.context.get("reject_code")) if rejected else None
        move = OrderTransition(
            account_id=account,
            order_id=order_id,
            from_state=ORDER_STATE_OF[_chart_state(step.from_state)],
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
        )
        if kind not in FILL_KINDS:
            return (await self._orders.transition(move)).event.seq
        done = await self._executions.commit_fill(_fill(step, move))
        if done is None and step.event == "EXEC":
            # The machine counted as new a fill its row holds: the row moved on under it (a COMMIT
            # that landed after the machine was rebuilt), so the facade rebuilds it again (S7).
            raise StaleOrderState(order_id, move.from_state)
        if done is None:
            raise ValueError(
                "the execution is stored already, so the machine counted it twice (S4)"
            )
        return done.event.seq

    async def _create(
        self, step: Step, account: UUID, order_id: UUID, to_state: LifecycleState
    ) -> int:
        order = self._expected.get(order_id)
        if order is None or to_state not in ("validated", "untracked"):
            raise ValueError("no registered order for this order's first row")
        _agrees(order, step, account)
        kind, source = event_kind(step)
        first = NewOrderEvent(
            kind=kind, source=source, event_ts=self._clock(), payload=step.payload
        )
        stored = replace(order, state=ORDER_STATE_OF[to_state], lifecycle_state=to_state)
        await self._orders.create(stored, first)
        del self._expected[order_id]
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
    SR-E29-03 matches), and for an `untracked` one its exchange order id."""
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
            step.to_state != "untracked" or order.exchange_order_id == ctx.get("exchange_order_id")
        )
    )
    if not same:
        raise ValueError("the registered order is not the order the machine holds")


def _at(raw: object, fallback: datetime) -> datetime:
    if raw is None:
        return fallback
    if type(raw) is not int or raw < 0:
        raise ValueError("an execution time is not microseconds since the epoch")
    return _EPOCH + timedelta(microseconds=raw)


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
