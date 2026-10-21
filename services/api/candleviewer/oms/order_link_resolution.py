"""Resolving an `order_link_id` on the exchange: §8.3 rules 3 and 6 (E29-T02, #846).

`place_or_adopt` sends one create and turns a duplicate-id rejection into the
exchange's own order for that id ("success-after-lookup"), never an error.
`adopt_or_resend` re-sends an ambiguous create only after a lookup (SR-E29-15).
`HistoryRetentionPolicy` tells the E29-T06 reconciler when an id is too old for
the exchange's order history to resolve.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol, cast

import structlog

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    OmsErrorCode,
)
from candleviewer.exchange.base.models import (
    AccountRef,
    ExchangeCapabilities,
    Order,
    OrderAck,
    PlaceOrderRequest,
)

from .errors import InvalidHistoryRetention, InvalidOrderLinkId

__all__ = [
    "DEMO_RETENTION_EXPIRED",
    "MIN_RETENTION_DAYS",
    "Adopted",
    "HistoryRetentionPolicy",
    "PlaceOutcome",
    "PlacementPort",
    "Sent",
    "Unresolved",
    "UnresolvedReason",
    "adopt_or_resend",
    "place_or_adopt",
]

DEMO_RETENTION_EXPIRED: Final = "DEMO_RETENTION_EXPIRED"
"""`reject_code` of an order closed because its id expired from history (rule 6)."""

MIN_RETENTION_DAYS: Final = 2
"""The shortest exchange retention rule 6 can work with: it expires an id after the retention
less one day, so with one day or less every id would count as unresolvable on creation."""

_DAY_US: Final = 86_400 * 1_000_000


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class PlacementPort(Protocol):
    """The `TradingPort` methods success-after-lookup uses; any `TradingPort` fits."""

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck: ...

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]: ...

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        exchange_order_id: str | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]: ...


@dataclass(frozen=True, slots=True)
class Sent:
    """The exchange answered this create; the caller branches on `ack.ok` (§8.4)."""

    ack: OrderAck


@dataclass(frozen=True, slots=True)
class Adopted:
    """The exchange's order under the id, after a duplicate-id rejection (`place_or_adopt`)
    or an ambiguous create (`adopt_or_resend`).

    It is found on the id alone (in the account; open orders also by symbol), so it is not
    yet proven ours. Before binding it to the row the caller checks every SR-E29-03 field
    (account, symbol, side, quantity, order type, price or trigger, reduce-only, attached
    stop), as B1's `is_duplicate_link_id_full_match` does; a mismatch is a squatted id
    (OM-S05) that goes to `held` (`is_link_id_mismatch`) and is never bound."""

    order: Order
    source: Literal["realtime", "history"]


type UnresolvedReason = Literal[
    "not_found", "lookup_failed", "history_expired", "resend_unconfirmed"
]


@dataclass(frozen=True, slots=True)
class Unresolved:
    """No lookup settled the id: the caller moves the order to `unknown`, and only
    reconciliation resolves it (§8.2 S1). `not_found` is a duplicate-id rejection
    neither lookup found; the others end `adopt_or_resend`, which sends nothing more. A
    `resend_unconfirmed` re-send met by a duplicate means the exchange holds an order under
    the id: reconciliation (E29-T06) binds it, after the full match of `Adopted`."""

    order_link_id: OrderLinkId
    reason: UnresolvedReason = "not_found"


type PlaceOutcome = Sent | Adopted | Unresolved


async def place_or_adopt(port: PlacementPort, request: PlaceOrderRequest) -> PlaceOutcome:
    """Send one create (rule 3): a duplicate-id rejection is adopted, not reported.

    The request goes out unchanged, so a retry sends the same `order_link_id`
    and the same native stop-loss. Every other error propagates: a transport
    failure after send (`AmbiguousResultError`) is the caller's `unknown`, never a
    resend under a new id, and any later re-send goes through `adopt_or_resend`.

    The id must be one the generator produced (`OUR_ID`). An `ext-` key never
    goes on the wire (§8.3), and any other id would come back from the adapter
    as a different `ext_key(orderId)` (§14.2 rule 11) and never pair with its
    row, so `InvalidOrderLinkId` is raised before anything is sent.

    Audit (C-2.9): this writes no audit record, no `order_events` row and no state
    change. Its log lines are diagnostics, and an audit never depends on log level, so
    the caller owes both records:

    - before the call, the intent: the order row and its write-ahead `order_events` row,
      committed ahead of the send (§8.4, §8.2 S8);
    - after it, the adoption: for `Adopted`, a record of the id, the `source` and the
      state taken from the exchange, in the same transaction as the state change where
      possible; for `Unresolved`, the move to `unknown` (§8.2 S1), written ahead like
      any other transition.
    """
    _require_our_id(request)
    try:
        ack = await port.place_order(request)
    except DuplicateClientIdError:
        return await _adopt(port, request)
    if ack.ok or ack.error_code != OmsErrorCode.DUPLICATE_CLIENT_ID:
        return Sent(ack)
    return await _adopt(port, request)


async def adopt_or_resend(
    port: PlacementPort,
    request: PlaceOrderRequest,
    *,
    retention: HistoryRetentionPolicy,
    created_at: TsUs,
    now: TsUs,
) -> PlaceOutcome:
    """Re-send a create whose result was ambiguous, after one lookup (SR-E29-15).

    The id found in open orders, then in history, is adopted. Only if neither shows
    it, and history still covers an id first sent at `created_at` (rule 6), is the
    request sent once more, unchanged (same id, same native stop). A failed lookup,
    an expired id, or a re-send met by a duplicate or another ambiguous result is
    `Unresolved`. Other errors of the re-send propagate, as in `place_or_adopt`, and
    so do `AuthError` and `ClockDriftError` from a lookup: they gate trading.

    For E29-T04: the only re-send after an ambiguous create (a restart re-driving the
    row, say), never from B1 `unknown` (INV-B1-e). The caller runs the synchronous gates
    (kill switch, live-enablement gate, risk caps) just before calling it, and never
    calls it for a `killed` or terminal row (C-2.21). It lets one driver resolve a row
    at a time, because two drivers could both miss and both re-send. It binds an `Adopted`
    order only on the SR-E29-03 full match (see `Adopted`), and audits as for
    `place_or_adopt`: the re-send intent ahead, its outcome after (C-2.9). One call is one
    attempt: a caller allowed several (a close retried with a lookup between, 24 §9.5.1)
    calls it once per attempt.
    """
    _require_our_id(request)
    link = request.order_link_id
    try:
        found = await _find(port, request)
    except (AuthError, ClockDriftError):
        raise
    except ExchangeError:
        return _not_resent(link, "lookup_failed")
    if found is not None:
        order, source = found
        _log().info("order_link_id_ambiguous_adopted", order_link_id=link, source=source)
        return Adopted(order=order, source=source)
    if retention.unresolvable_by_history(created_at=created_at, now=now):
        return _not_resent(link, "history_expired")
    try:
        ack = await port.place_order(request)
    except (AmbiguousResultError, DuplicateClientIdError):
        return _not_resent(link, "resend_unconfirmed")
    if ack.ok or ack.error_code != OmsErrorCode.DUPLICATE_CLIENT_ID:
        return Sent(ack)
    return _not_resent(link, "resend_unconfirmed")


def _require_our_id(request: PlaceOrderRequest) -> None:
    if OUR_ID.fullmatch(request.order_link_id) is None:
        raise InvalidOrderLinkId(f"not a generated order_link_id: {request.order_link_id!r}")


async def _adopt(port: PlacementPort, request: PlaceOrderRequest) -> Adopted | Unresolved:
    found = await _find(port, request)
    if found is not None:
        return _adopted(*found)
    _log().warning("order_link_id_duplicate_unresolved", order_link_id=request.order_link_id)
    return Unresolved(order_link_id=request.order_link_id)


async def _find(
    port: PlacementPort, request: PlaceOrderRequest
) -> tuple[Order, Literal["realtime", "history"]] | None:
    """One lookup round: the id in open orders, then in history.

    Both lookups pass the id filter (#846 Q5) and filter the results again, so
    no other order is ever adopted whatever a port returns.
    """
    link = request.order_link_id
    for order in await port.open_orders(request.account, request.symbol, order_link_id=link):
        if order.order_link_id == link:
            return order, "realtime"
    for order in await port.order_history(request.account, order_link_id=link):
        if order.order_link_id == link:
            return order, "history"
    return None


def _adopted(order: Order, source: Literal["realtime", "history"]) -> Adopted:
    _log().info(
        "order_link_id_duplicate_adopted",
        order_link_id=order.order_link_id,
        source=source,
        state=order.state,
    )
    return Adopted(order=order, source=source)


def _not_resent(link: OrderLinkId, reason: UnresolvedReason) -> Unresolved:
    _log().warning("order_link_id_ambiguous_unresolved", order_link_id=link, reason=reason)
    return Unresolved(order_link_id=link, reason=reason)


@dataclass(frozen=True, slots=True)
class HistoryRetentionPolicy:
    """Rule 6, for the E29-T06 reconciler: an id older than the exchange's order
    retention less one day cannot be resolved from history (demo keeps 7 days:
    6 days). The reconciler then closes the order: `rejected` with
    `DEMO_RETENTION_EXPIRED` (rule 6), or `cancelled` for an `untracked` row
    (§8.5 step 3b).

    Driven by `ExchangeCapabilities.order_retention_days`, never by an
    environment check (§14.2 rule 3); `None` means history never expires, and any
    other value is at least `MIN_RETENTION_DAYS`, or construction raises
    `InvalidHistoryRetention`.
    """

    retention_days: int | None

    def __post_init__(self) -> None:
        if self.retention_days is not None and self.retention_days < MIN_RETENTION_DAYS:
            raise InvalidHistoryRetention(
                f"retention_days must be None or at least {MIN_RETENTION_DAYS}, "
                f"got {self.retention_days}"
            )

    @classmethod
    def from_capabilities(cls, capabilities: ExchangeCapabilities) -> HistoryRetentionPolicy:
        return cls(retention_days=capabilities.order_retention_days)

    def unresolvable_by_history(self, *, created_at: TsUs, now: TsUs) -> bool:
        if self.retention_days is None:
            return False
        return now - created_at > (self.retention_days - 1) * _DAY_US
