"""B1's recovery from `order_events` (E29-T03 #847; 24-internal-schemas.md Sec.8.2, "Recovery").

`orders` is a projection of `order_events` (threat model OM-T03). `rebuild` folds an order's
events, in `seq` order, into the columns B1's write-ahead steps set, and the result equals the row
(`RebuiltOrder.of_row`). `replay_plan` names, off B1's static table, the trigger of each step the
events record, which the OMS facade replays to hydrate the order's machine
(`OrderMachines.hydrate`). Both are pure: no I/O, no clock, no interpreter (C-2.20).

The fold reads each event as B1's actions wrote it (`statechart.bindings.b01_order`):

* the first (`seq` 0): the order `VALIDATE`, `DISCOVERED` or `MATERIALISED` named, its identity
  and terms, and for one created outside the placement path (a discovered order, a recorded
  stop's TP/SL order) its exchange order id;
* a `place` ack (`ack`): the exchange order id it bound, its own or its lookup's (`adopt_ack`);
* a reconciliation finding (`reconcile_diff` into any state but `held`, or a fill that carries its
  execution): the exchange order id it names (`adopt_recon`);
* a fill (`fill`, `partial_fill`): its execution, applied again through `apply_execution`;
* an amend's result (`amend_ack`) that is `ok`: the terms it names, all or none (`adopt_amend`);
* a step into `rejected`: its `ret_code` and `ret_msg`, which are the reject columns
  (`OrderTransition`).

An exchange order id binds once, as B1 binds it; any other event moves the state only. A history
the fold cannot read raises `OrderHistoryRefused`: a gap in `seq`, a step whose `from_state` is not
the state before it or that leaves a final state (INV-2), a first event B1 did not write, or a fill
the order cannot absorb (OM-T04).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Context, Decimal
from itertools import pairwise
from typing import Any, Final, cast
from uuid import UUID

from jsonschema import Draft202012Validator

from candleviewer.statechart.bindings.b01_order import MAX_TEXT, SCHEMAS, Step
from candleviewer.storage.repositories.orders import (
    AMENDABLE,
    FILL_KINDS,
    LIFECYCLE_STATE_OF,
    LifecycleState,
    OrderEventRow,
    OrderRow,
    OrderState,
)

from .errors import ExecutionRefused, OrderHistoryRefused
from .execution import apply_fields
from .order_steps import event_kind

__all__ = ["FINALS", "RebuiltOrder", "Replayed", "rebuild", "recorded_outcomes", "replay_plan"]

#: B1's final `lifecycle` states (INV-2): no step leaves one.
FINALS: Final[frozenset[LifecycleState]] = frozenset(
    {"filled", "cancelled", "rejected", "expired", "killed"}
)
#: The first event's kind, and the state B1 creates the row in (24 Sec.8.4; S9; a recorded stop's
#: row, Sec.8.3 rule 7). Each kind creates one state, so the pair names the first event's trigger.
_FIRST: Final[Mapping[str, LifecycleState]] = {
    "local_create": "validated",
    "adopt": "untracked",
    "exchange_push": "submitted",
}
_SIDES: Final = {"buy": "Buy", "sell": "Sell"}
_TERMS: Final = ("price", "trigger_price", "take_profit", "stop_loss")
#: B1's money as its actions keep it (C6 text that numeric(38,18) holds).
_MONEY: Final = re.compile(r"-?[0-9]{1,20}(\.[0-9]{1,18})?")
_EXACT: Final = Context(prec=80)
#: A trigger the machine's own invoke answers, never one the facade sends.
_ANSWERS: Final = ("done.invoke.", "error.platform.")
_SCHEMAS: Final = {name: Draft202012Validator(schema) for name, schema in SCHEMAS.items()}


@dataclass(frozen=True, slots=True)
class RebuiltOrder:
    """The `orders` columns a fold of the order's events rebuilds, compared as the row holds them
    (money by value: the row's numeric(38,18) scale is not the fold's). `exec_ids`, the fills in
    the order they were applied, and `last_seq` are the fold's own, outside the comparison."""

    order_id: UUID
    account_id: UUID
    order_link_id: str
    symbol: str
    side: str
    reduce_only: bool
    lifecycle_state: LifecycleState
    state: OrderState
    qty: Decimal
    price: Decimal | None
    trigger_price: Decimal | None
    take_profit: Decimal | None
    stop_loss: Decimal | None
    exchange_order_id: str | None
    cum_exec_qty: Decimal
    cum_exec_value: Decimal
    avg_price: Decimal | None
    fee_paid: Decimal
    leaves_qty: Decimal
    reject_code: str | None
    reject_message: str | None
    exec_ids: tuple[str, ...] = field(default=(), compare=False)
    last_seq: int = field(default=-1, compare=False)

    @classmethod
    def of_row(cls, row: OrderRow) -> RebuiltOrder:
        """The same columns read off the row, its chart state as `lifecycle_state` keeps it."""
        return cls(
            order_id=row.id,
            account_id=row.exchange_account_id,
            order_link_id=row.order_link_id,
            symbol=row.symbol,
            side=row.side,
            reduce_only=row.reduce_only,
            lifecycle_state=row.lifecycle_state or LIFECYCLE_STATE_OF[row.state],
            state=row.state,
            qty=row.qty,
            price=row.price,
            trigger_price=row.trigger_price,
            take_profit=row.take_profit,
            stop_loss=row.stop_loss,
            exchange_order_id=row.exchange_order_id,
            cum_exec_qty=row.cum_exec_qty,
            cum_exec_value=row.cum_exec_value,
            avg_price=row.avg_price,
            fee_paid=row.fee_paid,
            leaves_qty=row.leaves_qty,
            reject_code=row.reject_code,
            reject_message=row.reject_message,
        )


def _money(raw: object) -> Decimal:
    if not isinstance(raw, str) or not _MONEY.fullmatch(raw):
        raise OrderHistoryRefused("a money value in the history is not B1's decimal text")
    return Decimal(raw)


def _term(raw: object) -> Decimal | None:
    return None if raw is None else _money(raw)


def _text(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise OrderHistoryRefused("an id in the history is not text")
    return raw


def _created(first: OrderEventRow) -> dict[str, Any]:
    """The order its first event names (`VALIDATE`'s, `DISCOVERED`'s or `MATERIALISED`'s
    `order`), with the exchange order id the latter two bind."""
    order = first.payload.get("order")
    if not isinstance(order, Mapping):
        raise OrderHistoryRefused("the first event does not name the order")
    try:
        identity = {"order_id": UUID(_text(order.get("order_id")))}
        identity |= {"account_id": UUID(_text(order.get("account_id")))}
    except ValueError:
        raise OrderHistoryRefused("the first event names no order or account id") from None
    reduce_only = order.get("reduce_only", False)
    if identity["order_id"] != first.order_id or not isinstance(reduce_only, bool):
        raise OrderHistoryRefused("the first event names another order, or no reduce_only")
    side = _SIDES.get(str(order.get("side")))
    if side is None:
        raise OrderHistoryRefused("the first event names no side")
    found = order.get("exchange_order_id") if _FIRST[first.kind] != "validated" else None
    return identity | {
        "order_link_id": _text(order.get("order_link_id")),
        "symbol": _text(order.get("symbol")),
        "side": side,
        "reduce_only": reduce_only,
        "qty": _money(order.get("qty")),
        **{key: _term(order.get(key)) for key in _TERMS},
        "exchange_order_id": None if found is None else _text(found),
        "cum_exec_qty": Decimal(0),
        "cum_exec_value": Decimal(0),
        "avg_price": None,
        "fee_paid": Decimal(0),
        "reject_code": None,
        "reject_message": None,
    }


def _bind(out: dict[str, Any], raw: object) -> None:
    """`b01_order._bind`: an exchange order id (text of 1 to `MAX_TEXT` characters) binds once; a
    later, different one is not taken."""
    if out["exchange_order_id"] is None and isinstance(raw, str) and 0 < len(raw) <= MAX_TEXT:
        out["exchange_order_id"] = raw


def _fill(out: dict[str, Any], execution: Mapping[str, Any], seen: list[str]) -> None:
    """S4: an execution applied once, through the arithmetic B1 applied it with."""
    exec_id = execution.get("exec_id")
    if not isinstance(exec_id, str) or exec_id in seen:
        raise OrderHistoryRefused("a fill names no exec_id, or one the history applied (S4)")
    fill = {key: _money(execution.get(key)) for key in ("qty", "price", "fee", "fee_rate")}
    totals = {"qty": out["qty"], "filled_qty": out["cum_exec_qty"]}
    totals |= {"cum_exec_value": out["cum_exec_value"], "fee_paid": out["fee_paid"]}
    try:
        after = apply_fields(totals, fill)
    except ExecutionRefused:
        raise OrderHistoryRefused("a fill the order cannot absorb (OM-T04)") from None
    out.update(
        cum_exec_qty=after["filled_qty"],
        cum_exec_value=after["cum_exec_value"],
        fee_paid=after["fee_paid"],
        avg_price=after["avg_price"],
    )
    seen.append(exec_id)


def _amend(out: dict[str, Any], terms: object) -> None:
    """`adopt_amend`: an accepted amend's terms, all or none; one that puts `qty` under the filled
    quantity (INV-1), or names a term that is not money above zero, keeps the prior order."""
    if not isinstance(terms, Mapping):
        return
    try:
        named = {key: _money(terms[key]) for key in AMENDABLE if terms.get(key) is not None}
    except OrderHistoryRefused:
        return
    if any(value <= 0 for value in named.values()):
        return
    if named.get("qty", out["qty"]) < out["cum_exec_qty"]:
        return
    out.update(named)


def _step(out: dict[str, Any], event: OrderEventRow, seen: list[str]) -> None:
    """What one step after the first wrote besides its state (module docstring)."""
    payload = event.payload
    if event.kind in FILL_KINDS:
        carried = payload.get("execution")
        if isinstance(carried, Mapping):  # a reconciliation finding with its execution
            _bind(out, payload.get("exchange_order_id"))
        _fill(out, carried if isinstance(carried, Mapping) else payload, seen)
    elif event.kind == "ack":
        lookup = payload.get("lookup")
        raw = payload.get("exchange_order_id")
        if raw is None and isinstance(lookup, Mapping):
            raw = lookup.get("exchange_order_id")
        _bind(out, raw)
    elif event.kind == "reconcile_diff" and event.to_state != "held":
        _bind(out, payload.get("exchange_order_id"))
    elif event.kind == "amend_ack" and payload.get("ok") is True:
        _amend(out, payload.get("terms"))
    if event.to_state == "rejected":
        out["reject_code"], out["reject_message"] = event.ret_code, event.ret_msg


def rebuild(events: Sequence[OrderEventRow]) -> RebuiltOrder:
    """The order's row as its events, in `seq` order, rebuild it (module docstring)."""
    if not events or events[0].seq != 0:
        raise OrderHistoryRefused("the history does not start at the order's first event")
    first = events[0]
    if first.from_state is None and first.to_state is not None:
        created = _FIRST.get(first.kind) == LIFECYCLE_STATE_OF[first.to_state]
    else:
        created = False
    if not created:
        raise OrderHistoryRefused("the first event is not one B1 creates an order with")
    out, state = _created(first), cast(OrderState, first.to_state)
    seen: list[str] = []
    for index, event in enumerate(events[1:], start=1):
        if event.seq != index:
            raise OrderHistoryRefused(f"the history has no event at seq {index}")
        if event.to_state is None:  # an event with no step (`OrderEventStore.append`)
            continue
        if event.from_state != state or LIFECYCLE_STATE_OF[state] in FINALS:
            raise OrderHistoryRefused(f"the step at seq {index} leaves no state the order held")
        _step(out, event, seen)
        state = event.to_state
    leaves = _EXACT.subtract(out["qty"], out["cum_exec_qty"])
    chart = LIFECYCLE_STATE_OF[state]
    return RebuiltOrder(
        **out,
        lifecycle_state=chart,
        state=state,
        leaves_qty=leaves,
        exec_ids=tuple(seen),
        last_seq=events[-1].seq,
    )


@dataclass(frozen=True, slots=True)
class Replayed:
    """One recorded step to replay on a fresh machine: its event, the trigger B1's table names for
    it, and the chart state it entered. The machine's own invoke answers a service's result
    (`answered`); the facade sends any other trigger, with the recorded payload."""

    row: OrderEventRow
    trigger: str
    state: LifecycleState

    @property
    def answered(self) -> bool:
        return self.trigger.startswith(_ANSWERS)


def _recorded_as(trigger: str, event: OrderEventRow, source: str, target: str) -> bool:
    """B1 records *trigger* as *event*: the kind and source its step writes (`event_kind`), and a
    payload its closed schema takes (a service's result has none)."""
    probe = Step(None, None, None, source, target, trigger, event.payload, {})
    try:
        if event_kind(probe) != (event.kind, event.source):
            return False
    except ValueError:
        return False
    validator = _SCHEMAS.get(trigger)
    return validator is None or bool(validator.is_valid(event.payload))


def replay_plan(
    events: Sequence[OrderEventRow], triggers: Mapping[tuple[str, str], frozenset[str]]
) -> tuple[Replayed, ...]:
    """The steps *events* record, each with the one trigger of B1's table (`Legality.triggers`)
    that writes it. An exchange fact and a service's result can write alike (an `AMEND_REJECTED`
    and an `amend` result): the fact is the one whose closed schema takes the payload, as a
    service's result names its outcome (`ok`, `terms`), which no fact's schema admits. A step no
    single trigger writes raises `OrderHistoryRefused`."""
    plan: list[Replayed] = []
    for event in events:
        if event.to_state is None:
            continue
        source = "draft" if event.from_state is None else LIFECYCLE_STATE_OF[event.from_state]
        target = LIFECYCLE_STATE_OF[event.to_state]
        edge = sorted(triggers.get((source, target), ()))
        named = [trigger for trigger in edge if _recorded_as(trigger, event, source, target)]
        if len(named) > 1:
            named = [trigger for trigger in named if not trigger.startswith(_ANSWERS)]
        if len(named) != 1:
            raise OrderHistoryRefused(f"the step at seq {event.seq} has no single B1 trigger")
        plan.append(Replayed(event, named[0], target))
    return tuple(plan)


def recorded_outcomes(plan: Sequence[Replayed]) -> dict[str, Mapping[str, Any] | str]:
    """The outcome each replayed service answers, keyed as B1 keys a command attempt
    (`<invoke id>:<seq of the step that entered its state>`, `b01_order._command`): the result a
    `done.invoke.*` step recorded, or the class of what an `error.platform.*` step's call raised."""
    out: dict[str, Mapping[str, Any] | str] = {}
    for before, step in pairwise(plan):
        if step.answered:
            kind, _, invoke = step.trigger.rpartition(".")
            key = f"{invoke}:{before.row.seq}"
            failure = step.row.payload.get("error")
            done = kind == "done.invoke"
            out[key] = dict(step.row.payload) if done else str(failure or "Exception")
    return out
