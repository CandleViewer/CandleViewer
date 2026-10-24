"""`placeOrder`'s `202` body, `OrderAcceptance` (E29-T04 #913 slice 3; 22 `OrderAcceptance`).

`first_acceptance` renders a first answer from the rows the pipeline's first persist wrote
(`SubmitOutcome.written`) and the state B1 gave the order after its create (`lifecycle`), with no
read after the send, where a store failure is never a 503 (24 Sec.8.4): the order in that state,
and an entry's group as written with its leg as `OrderSubmission._settle_group` leaves it
(`submitted`, or as written for a `held` order). `replayed_acceptance` renders a repeat from the
rows as read now. An entry's one-leg group holds the order in its leg's `order_details`; a
reduce-only order joins none (`order`). `reconciling` is true while the order is unresolved
(`UNRESOLVED`) or its state could not be read. Each object carries members of its 22 schema only
(SEC-S3D-03): never the request's fingerprint, the leg's profile snapshot or a column 22 does not
serve.

A plain module with no router, as `api/order_problems.py` is: the route calls it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final, cast
from uuid import UUID

from candleviewer.accounts.trade_groups import TradeGroupWithLegs
from candleviewer.domain.primitives import Environment
from candleviewer.oms.submit import RECONCILING, SubmitOutcome
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrder, OrderRow

__all__ = ["UNRESOLVED", "first_acceptance", "order_body", "replayed_acceptance"]

#: The B1 states whose create has no known outcome yet (22 `OrderAcceptance.reconciling`).
UNRESOLVED: Final = frozenset({"validated", "submitting", "unknown", "quarantined"})
_STORED: Final = cast(Mapping[str, str], ORDER_STATE_OF)
_DIRECTIONS: Final[Mapping[int, str]] = {1: "rise", 2: "fall"}

type Body = dict[str, object]


def _text(value: Decimal | None) -> str | None:
    """22 `Decimal`: plain notation, never an exponent."""
    return None if value is None else format(value, "f")


def order_body(
    row: NewOrder | OrderRow, group_id: UUID | None, env: Environment, state: str, chart: str | None
) -> Body:
    """22 `Order`: the row's own members, in 22's vocabulary; the exit routes' `202` too (E29-T04
    slice 4)."""
    leg_id = row.trade_group_leg_id
    return {
        "id": str(row.id), "exchange_account_id": str(row.exchange_account_id),
        "trade_group_id": None if group_id is None else str(group_id),
        "trade_group_leg_id": None if leg_id is None else str(leg_id),
        "order_link_id": row.order_link_id, "exchange_order_id": row.exchange_order_id,
        "symbol": row.symbol, "side": row.side.lower(), "order_type": row.order_type.lower(),
        "intent": row.intent, "provenance": row.provenance, "state": state,
        "lifecycle_state": chart, "qty": _text(row.qty), "filled_qty": _text(row.cum_exec_qty),
        "price": _text(row.price), "avg_fill_price": _text(row.avg_price),
        "time_in_force": row.time_in_force, "reduce_only": row.reduce_only,
        "close_on_trigger": row.close_on_trigger, "position_idx": row.position_idx,
        "trigger_price": _text(row.trigger_price), "trigger_by": row.trigger_by,
        "trigger_direction": _DIRECTIONS.get(row.trigger_direction or 0),
        "take_profit": _text(row.take_profit), "stop_loss": _text(row.stop_loss),
        "tpsl_mode": row.tpsl_mode, "environment": env, "is_paper": row.is_paper,
    }  # fmt: skip


def _leg(
    leg_id: UUID, group_id: UUID, account_id: UUID, profile_id: UUID | None, status: str,
    sequence_no: int, target_qty: Decimal, order: Body,
) -> Body:  # fmt: skip
    """22 `TradeGroupLeg`, with its order in `order_details` when it is the leg's."""
    orders = [order] if order["trade_group_leg_id"] == str(leg_id) else []
    return {
        "id": str(leg_id), "trade_group_id": str(group_id), "exchange_account_id": str(account_id),
        "account_profile_id": None if profile_id is None else str(profile_id), "status": status,
        "sequence_no": sequence_no, "target_qty": _text(target_qty),
        "orders": [o["id"] for o in orders], "order_details": orders,
    }  # fmt: skip


def _group(
    group_id: UUID, ref: object, symbol: str, side: str, status: str, created_by: UUID,
    legs: Sequence[Body], intent: str,
) -> Body:  # fmt: skip
    """22 `TradeGroup`: the members a client reads its one-leg group by, with its order's `intent`
    as 22's `entry` example shows (the group row has none of its own)."""
    # SR-E28-21: no `shows_private_fields` check, as an anchor's principal is its group's creator.
    return {
        "id": str(group_id), "client_group_ref": str(ref), "symbol": symbol, "side": side.lower(),
        "intent": intent, "status": status, "created_by": str(created_by), "legs": list(legs),
    }  # fmt: skip


def first_acceptance(outcome: SubmitOutcome, env: Environment) -> Body:
    """A first `202` (module docstring); `ValueError` for an outcome with no written rows. Its
    order's `exchange_order_id` is null: the persist wrote the row before the send, and nothing is
    read after it."""
    written, chart = outcome.written, outcome.lifecycle
    if written is None or outcome.replayed:
        raise ValueError("a first answer is rendered from the rows its persist wrote")
    row, group = written.order, written.group
    order = order_body(row, outcome.trade_group_id, env, _STORED.get(chart or "", row.state), chart)
    answer: Body = {"trade_group": None, "order": None, "reconciling": chart in UNRESOLVED}
    if group is None:
        return answer | {"order": order}
    settled = None if chart == "held" else "submitted"  # as `_settle_group` leaves the leg
    legs: list[Body] = []
    for leg in written.legs:
        legs.append(_leg(
            leg.id, group.id, leg.exchange_account_id, leg.account_profile_id,
            settled or leg.status, leg.sequence_no, leg.target_qty, order,
        ))  # fmt: skip
    rendered = _group(
        group.id, group.client_group_ref, group.symbol, group.side, group.status,
        group.created_by, legs, row.intent,
    )  # fmt: skip
    return answer | {"trade_group": rendered}


def replayed_acceptance(
    row: OrderRow, found: TradeGroupWithLegs | None, outcome: SubmitOutcome, env: Environment
) -> Body:
    """A repeat's `202` from the rows as read now: `reconciling` too while the pipeline's
    reconciled state (`OrderSubmission.answer_replay`) says so. `ValueError` unless `found` is the
    group `outcome` names, none for a reduce-only order."""
    group_id = None if found is None else found.group.group_id
    if group_id != outcome.trade_group_id:
        raise ValueError("a repeat is rendered with the group its outcome names, or none")
    chart = row.lifecycle_state
    unresolved = outcome.lifecycle == RECONCILING or chart is None or chart in UNRESOLVED
    order = order_body(row, group_id, env, row.state, chart)
    answer: Body = {"trade_group": None, "order": None, "reconciling": unresolved}
    if found is None:
        return answer | {"order": order}
    group = found.group
    legs: list[Body] = []
    for leg in found.legs:
        legs.append(_leg(
            leg.leg_id, leg.group_id, leg.account_id, leg.account_profile_id, leg.status,
            leg.sequence_no, leg.target_qty, order,
        ))  # fmt: skip
    rendered = _group(
        group.group_id, group.client_group_ref, group.symbol, group.side, group.status,
        group.created_by, legs, row.intent,
    )  # fmt: skip
    return answer | {"trade_group": rendered}
