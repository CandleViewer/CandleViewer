"""The private stream's rows as B1 events (E29-T05 #848; 24-internal-schemas.md Sec.8.12).

Pure: no I/O, no clock, no interpreter (C-2.20), and on the hot-path contract, so it imports no
statechart module, directly or through another. `route` says what one row of an account's stream
is for: an order row or a trade execution goes to pairing (`oms.pairing`) with the B1 event its
paired row then takes, or none; a position row is a protection reading; a fast execution, a
non-trade execution and a wallet row give B1 nothing. The payload builders write B1's closed
schemas, which the tests hold them to, with the paired row's ids, money as exact decimal text and
every order row's time from the venue's own clock (`push_time_ms`). Nothing here pairs, sends or
logs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

from candleviewer.domain.primitives import TsUs
from candleviewer.exchange.base.models import (
    Execution,
    FastExecution,
    Order,
    Position,
    PrivateEvent,
)

from .ports import PositionKey, ProtectionReading

__all__ = [
    "EXPIRING", "IMMEDIATE", "ORDER_STATUS_EVENTS",
    "ForPairing", "ForProtection", "NoB1Event", "OrderRowEvent", "PairedEvent", "Route",
    "StreamEvent",
    "exec_payload", "money_text", "order_event", "push_payload", "push_time_ms", "reading",
    "reading_payload", "route",
]  # fmt: skip

type OrderRowEvent = Literal["TRIGGERED", "EXPIRE", "REMOTE_CANCELLED"]
type PairedEvent = Literal["EXEC", "TRIGGERED", "EXPIRE", "REMOTE_CANCELLED"]
#: Every B1 event this module names: each one the facade's `push` takes (a test pins it).
type StreamEvent = Literal[
    "EXEC", "TRIGGERED", "EXPIRE", "REMOTE_CANCELLED", "SL_OBSERVED", "SL_LOST"
]

#: 24 Sec.8.12's order rows, one entry per status the adapter reads (a test pins the set); None
#: where a fill moves the order, never its order row.
ORDER_STATUS_EVENTS: Final[Mapping[str, OrderRowEvent | None]] = MappingProxyType({
    "new": None, "untriggered": None, "partially_filled": None, "filled": None,
    "triggered": "TRIGGERED",
    "cancelled": "REMOTE_CANCELLED", "partially_filled_canceled": "REMOTE_CANCELLED",
    "deactivated": "REMOTE_CANCELLED", "rejected": "REMOTE_CANCELLED",
})  # fmt: skip
#: The Q4 ruling: these ends are EXPIRE exactly for an IMMEDIATE order.
EXPIRING: Final = frozenset({"cancelled", "partially_filled_canceled"})
IMMEDIATE: Final = frozenset({"ioc", "fok"})


@dataclass(frozen=True, slots=True)
class ForPairing:
    """An order row or a trade execution for `oms.pairing.pair` to name its row, which then takes
    `event` (none where a fill moves the order). A status outside the table is `unmapped`: paired
    like any order, marked, never dropped (24 Sec.8.12)."""

    push: Order | Execution
    event: PairedEvent | None
    unmapped: bool = False


@dataclass(frozen=True, slots=True)
class ForProtection:
    """A position row: the position it names and the protection reading it gives."""

    key: PositionKey
    reading: ProtectionReading


@dataclass(frozen=True, slots=True)
class NoB1Event:
    """A row B1 takes nothing from, and why."""

    reason: Literal["not_a_trade", "fast_execution", "wallet"]


type Route = ForPairing | ForProtection | NoB1Event


def order_event(order: Order) -> OrderRowEvent | None:
    """The B1 event the paired row takes; `ValueError`, naming no value, for an unmapped status."""
    if order.state not in ORDER_STATUS_EVENTS:
        raise ValueError("an order status 24 Sec.8.12 does not map")
    if order.state in EXPIRING and order.time_in_force in IMMEDIATE:
        return "EXPIRE"
    return ORDER_STATUS_EVENTS[order.state]


def route(event: PrivateEvent) -> Route:
    """What one row of the account's stream is for."""
    p = event.payload
    if isinstance(p, Order):
        if p.state not in ORDER_STATUS_EVENTS:
            return ForPairing(p, None, unmapped=True)
        return ForPairing(p, order_event(p))
    if isinstance(p, Execution):
        return ForPairing(p, "EXEC") if p.exec_type == "trade" else NoB1Event("not_a_trade")
    if isinstance(p, Position):
        return ForProtection(PositionKey(p.account_id, p.symbol, p.position_idx), reading(p))
    if isinstance(p, FastExecution):
        return NoB1Event("fast_execution")
    return NoB1Event("wallet")  # PrivateEvent's validator: the payload is its kind's


def push_time_ms(order: Order, ts_event: TsUs) -> int:
    """An order row's `updated_time` in ms (24 Sec.8.12): the venue's own time of its last change,
    never the time the row was received, so a read after an older push cannot win on its receipt
    time. Only an order with none (`updated_at` is None: its source sends none) takes `ts_event`."""
    stamp = ts_event if order.updated_at is None else order.updated_at
    return stamp // 1_000


def push_payload(order: Order, *, order_link_id: str, ts_event: TsUs) -> dict[str, object]:
    """B1's `_PUSH` for an order row, under the paired row's own `order_link_id` (24 Sec.8.3 rule
    7): the status as the adapter gives it, and the cumulative fill an end waits for (INV-B1-k)."""
    return {
        "exchange_order_id": order.exchange_order_id,
        "order_link_id": order_link_id,
        "order_status": order.state,
        "cum_exec_qty": money_text(order.filled_qty),
        "updated_time": push_time_ms(order, ts_event),
    }


def exec_payload(execution: Execution, *, order_id: UUID, order_link_id: str) -> dict[str, object]:
    """B1's `EXEC` for a trade execution: the paired row's `order_id` and `order_link_id`, the
    execution's own account, symbol and side (B1's `_pairs` refuses a fill that disagrees with its
    order), and the fill exactly. Nothing is sanitised: B1's `text_id` judges every id."""
    payload: dict[str, object] = {
        "exec_id": execution.exec_id, "exchange_order_id": execution.exchange_order_id,
        "order_id": str(order_id), "order_link_id": order_link_id,  # the paired ROW's
        "account_id": str(execution.account_id), "symbol": execution.symbol,
        "side": execution.side,  # the execution's own: B1's pairing check holds it to the order's
        "qty": money_text(execution.qty), "price": money_text(execution.price),
        "fee": money_text(execution.fee), "fee_rate": money_text(execution.fee_rate),
        "closed_pnl": None if execution.closed_pnl is None else money_text(execution.closed_pnl),
        "exec_type": execution.exec_type, "is_maker": execution.is_maker,
        "ts_exec": execution.ts_exec, "ts_ingest": execution.ts_ingest, "seq": execution.seq,
    }  # fmt: skip
    if execution.fee_currency:  # B1 keeps no empty text, and the step writer stores USDT
        payload["fee_currency"] = execution.fee_currency
    return payload


def reading(position: Position) -> ProtectionReading:
    """`SL_LOST` exactly for an open position with no stop, so a flat row never is (C-2.6). The stop
    is the position's own: one held only by a Partial-mode order reads as none (24 Sec.8.12)."""
    lost = position.qty > 0 and position.stop_loss is None
    return ProtectionReading(
        event="SL_LOST" if lost else "SL_OBSERVED",
        updated_time=position.updated_at // 1_000,
        stop_loss=position.stop_loss,
        size=position.qty,
    )


def reading_payload(value: ProtectionReading) -> dict[str, object]:
    """B1's `_READING` for `value`."""
    stop = None if value.stop_loss is None else money_text(value.stop_loss)
    return {"updated_time": value.updated_time, "stop_loss": stop, "size": money_text(value.size)}


def money_text(value: Decimal) -> str:
    """`value` as exact fixed-point text with no trailing zero, as B1 keeps money. Never through
    `domain.plain_decimal`: it rounds to 28 digits, and numeric(38,18) holds 38."""
    out = format(value, "f")
    out = out.rstrip("0").rstrip(".") if "." in out else out
    return "0" if out == "-0" else out
