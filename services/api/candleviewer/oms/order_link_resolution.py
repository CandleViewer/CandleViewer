"""Resolving an `order_link_id` on the exchange: §8.3 rules 3 and 6 (E29-T02, #846).

`place_or_adopt` sends one create and turns a duplicate-id rejection into the
exchange's own order for that id ("success-after-lookup"), never an error.
`HistoryRetentionPolicy` tells the E29-T06 reconciler when an id is too old for
the exchange's order history to resolve.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol, cast

import structlog

from candleviewer.domain.primitives import OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.errors import DuplicateClientIdError, OmsErrorCode
from candleviewer.exchange.base.models import (
    AccountRef,
    ExchangeCapabilities,
    Order,
    OrderAck,
    PlaceOrderRequest,
)

__all__ = [
    "DEMO_RETENTION_EXPIRED",
    "Adopted",
    "HistoryRetentionPolicy",
    "PlaceOutcome",
    "PlacementPort",
    "Sent",
    "Unresolved",
    "place_or_adopt",
]

DEMO_RETENTION_EXPIRED: Final = "DEMO_RETENTION_EXPIRED"
"""`reject_code` of an order closed because its id expired from history (rule 6)."""

_DAY_US: Final = 86_400 * 1_000_000


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class PlacementPort(Protocol):
    """The `TradingPort` methods success-after-lookup uses; any `TradingPort` fits."""

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck: ...

    async def open_orders(
        self, account: AccountRef, symbol: Symbol | None = None
    ) -> Sequence[Order]: ...

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]: ...


@dataclass(frozen=True, slots=True)
class Sent:
    """The exchange answered this create; the caller branches on `ack.ok` (§8.4)."""

    ack: OrderAck


@dataclass(frozen=True, slots=True)
class Adopted:
    """A duplicate-id rejection, resolved to the exchange's order for that id."""

    order: Order
    source: Literal["realtime", "history"]


@dataclass(frozen=True, slots=True)
class Unresolved:
    """A duplicate-id rejection neither lookup found: the caller moves the order to
    `unknown`, and only reconciliation resolves it (§8.2 S1)."""

    order_link_id: OrderLinkId


type PlaceOutcome = Sent | Adopted | Unresolved


async def place_or_adopt(port: PlacementPort, request: PlaceOrderRequest) -> PlaceOutcome:
    """Send one create (rule 3): a duplicate-id rejection is adopted, not reported.

    The request goes out unchanged, so a retry sends the same `order_link_id`
    and the same native stop-loss. Every other error propagates: a transport
    failure after send is the caller's `unknown`, never a resend under a new id.
    """
    try:
        ack = await port.place_order(request)
    except DuplicateClientIdError:
        return await _adopt(port, request)
    if ack.ok or ack.error_code != OmsErrorCode.DUPLICATE_CLIENT_ID:
        return Sent(ack)
    return await _adopt(port, request)


async def _adopt(port: PlacementPort, request: PlaceOrderRequest) -> Adopted | Unresolved:
    """Look the id up in open orders, then in history, and adopt what is found.

    Open orders are filtered here until `open_orders` takes an id filter (#846
    Q5); history results are filtered again so no other order is ever adopted.
    """
    link = request.order_link_id
    for order in await port.open_orders(request.account, request.symbol):
        if order.order_link_id == link:
            return _adopted(order, "realtime")
    for order in await port.order_history(request.account, order_link_id=link):
        if order.order_link_id == link:
            return _adopted(order, "history")
    _log().warning("order_link_id_duplicate_unresolved", order_link_id=link)
    return Unresolved(order_link_id=link)


def _adopted(order: Order, source: Literal["realtime", "history"]) -> Adopted:
    _log().info(
        "order_link_id_duplicate_adopted",
        order_link_id=order.order_link_id,
        source=source,
        state=order.state,
    )
    return Adopted(order=order, source=source)


@dataclass(frozen=True, slots=True)
class HistoryRetentionPolicy:
    """Rule 6, for the E29-T06 reconciler: an id older than the exchange's order
    retention less one day cannot be resolved from history, so its order closes
    as `rejected` with `DEMO_RETENTION_EXPIRED` (demo keeps 7 days: 6 days).

    Driven by `ExchangeCapabilities.order_retention_days`, never by an
    environment check (§14.2 rule 3); `None` means history never expires.
    """

    retention_days: int | None

    @classmethod
    def from_capabilities(cls, capabilities: ExchangeCapabilities) -> HistoryRetentionPolicy:
        return cls(retention_days=capabilities.order_retention_days)

    def unresolvable_by_history(self, *, created_at: TsUs, now: TsUs) -> bool:
        if self.retention_days is None:
            return False
        return now - created_at > (self.retention_days - 1) * _DAY_US
